import dataclasses

import jax
import flax.linen as nn
import jax.numpy as np
import tensorflow_probability.substrates.jax as tfp

from models.diffusion_utils import variance_preserving_map, alpha, sigma2, get_timestep_embedding
from models.diffusion_utils import NoiseScheduleScalar, NoiseScheduleFixedLinear
from models.transformer import Transformer

tfd = tfp.distributions


class ResNet(nn.Module):
    d_input: int
    n_layers: int = 1
    d_hidden: int = 512

    @nn.compact
    def __call__(self, x, cond=None):
        assert x.shape[-1] == self.d_input, "Input size mis-specified."
        z = x
        for _ in range(self.n_layers):
            h = nn.gelu(nn.LayerNorm()(z))
            h = nn.Dense(self.d_hidden)(h)
            if cond is not None:
                h += nn.Dense(self.d_hidden, use_bias=False)(cond[:, None, :])  # Project context to hidden size and add
            h = nn.gelu(nn.LayerNorm()(h))
            h = nn.Dense(self.d_input, kernel_init=jax.nn.initializers.zeros)(h)
            z = z + h  # Residual connection
        return z


class Encoder(nn.Module):
    d_hidden: int = 32
    n_layers: int = 3
    d_embedding: int = 8
    latent_diffusion: bool = True

    @nn.compact
    def __call__(self, x, cond=None):
        if self.latent_diffusion:
            x = nn.Dense(self.d_hidden)(x)
            x = ResNet(d_input=self.d_hidden, n_layers=self.n_layers, d_hidden=int(4 * self.d_hidden))(x, cond=cond)
            x = nn.Dense(self.d_embedding)(x)
        return x


class Decoder(nn.Module):
    d_hidden: int = 32
    n_layers: int = 3
    d_output: int = 3
    noise_scale: float = 1.0e-3
    latent_diffusion: bool = True

    @nn.compact
    def __call__(self, z, cond=None):
        if self.latent_diffusion:
            z = nn.Dense(self.d_hidden)(z)
            z = ResNet(d_input=self.d_hidden, n_layers=self.n_layers, d_hidden=int(4 * self.d_hidden))(z, cond=cond)
            z = nn.Dense(self.d_output)(z)
        return tfd.Normal(loc=z, scale=self.noise_scale)


class ScoreNet(nn.Module):
    d_embedding: int = 8
    d_t_embedding: int = 32
    transformer_dict: dict = dataclasses.field(default_factory=lambda: {"d_model": 256, "d_mlp": 512, "n_layers": 4, "n_heads": 4, "flash_attention": True})

    @nn.compact
    def __call__(self, z, t, conditioning, mask):

        assert np.isscalar(t) or len(t.shape) == 0 or len(t.shape) == 1
        t = t * np.ones(z.shape[0])  # Ensure t is a vector

        t_embedding = get_timestep_embedding(t, self.d_t_embedding)  # Timestep embeddings

        if conditioning is not None:
            cond = np.concatenate([t_embedding, conditioning], axis=-1)  # Concatenate with conditioning context
        else:
            cond = t_embedding

        # Pass context through a small MLP before passing into transformer
        cond = nn.gelu(nn.Dense(features=self.d_embedding * 8)(cond))
        cond = nn.gelu(nn.Dense(features=self.d_embedding * 8)(cond))
        cond = nn.Dense(self.d_embedding)(cond)

        h = Transformer(n_input=self.d_embedding, **self.transformer_dict)(z, cond, mask)

        return z + h


class VariationalDiffusionModel(nn.Module):
    timesteps: int = 1000
    gamma_min: float = -3.0
    gamma_max: float = 3.0
    d_embedding: int = 8
    d_hidden_encoding: int = 256
    antithetic_time_sampling: bool = False
    n_layers: int = 4
    noise_schedule: str = "learned_linear"  # "learned_linear" or "scalar"
    d_feature: int = 3
    noise_scale: float = 1.0e-3
    latent_diffusion: bool = True
    d_t_embedding: int = 32
    transformer_dict: dict = dataclasses.field(default_factory=lambda: {"d_model": 256, "d_mlp": 512, "n_layers": 4, "n_heads": 4, "flash_attention": True})
    n_classes: int = 0

    def setup(self):

        if self.noise_schedule == "learned_linear":
            self.gamma = NoiseScheduleFixedLinear(gamma_min=self.gamma_min, gamma_max=self.gamma_max)
        elif self.noise_schedule == "scalar":
            self.gamma = NoiseScheduleScalar(gamma_min=self.gamma_min, gamma_max=self.gamma_max)

        if self.latent_diffusion:
            embedding_dim = self.d_embedding
        else:
            embedding_dim = self.d_feature

        self.score_model = ScoreNet(d_t_embedding=self.d_t_embedding, d_embedding=embedding_dim, transformer_dict=self.transformer_dict)
        self.encoder = Encoder(d_hidden=int(4 * self.d_hidden_encoding), n_layers=self.n_layers, d_embedding=embedding_dim, latent_diffusion=self.latent_diffusion)
        self.decoder = Decoder(d_hidden=int(4 * self.d_hidden_encoding), n_layers=self.n_layers, d_output=self.d_feature, noise_scale=self.noise_scale, latent_diffusion=self.latent_diffusion)

        # Embedding for class and context
        if self.n_classes > 0:
            self.embedding_class = nn.Embed(self.n_classes, self.d_hidden_encoding)
        self.embedding_context = nn.Dense(self.d_hidden_encoding)

    def gammat(self, t):
        return self.gamma(t)

    def recon_loss(self, x, f, cond):
        """The reconstruction loss measures the gap in the first step.
        We measure the gap from encoding the image to z_0 and back again.
        """
        g_0 = self.gamma(0.0)
        eps_0 = jax.random.normal(self.make_rng("sample"), shape=f.shape)
        z_0 = variance_preserving_map(f, g_0, eps_0)
        z_0_rescaled = z_0 / alpha(g_0)
        loss_recon = -self.decode(z_0_rescaled, cond).log_prob(x)
        return loss_recon

    def latent_loss(self, f):
        """The latent loss measures the gap in the last step, this is the KL
        divergence between the final sample from the forward process and starting
        distribution for the reverse process, here taken to be a N(0,1).
        """
        g_1 = self.gamma(1.0)
        var_1 = sigma2(g_1)
        mean1_sqr = (1.0 - var_1) * np.square(f)
        loss_klz = 0.5 * (mean1_sqr + var_1 - np.log(var_1) - 1.0)
        return loss_klz

    def diffusion_loss(self, t, f, cond, mask):
        """The diffusion loss measures the gap in the intermediate steps."""

        # Sample z_t
        g_t = self.gamma(t)
        eps = jax.random.normal(self.make_rng("sample"), shape=f.shape)
        z_t = variance_preserving_map(f, g_t[:, None], eps)

        eps_hat = self.score_model(z_t, g_t, cond, mask)  # Compute predicted noise

        loss_diff_mse = np.square(eps - eps_hat)  # Compute MSE of predicted noise

        # Loss for finite depth T, i.e. discrete time
        T = self.timesteps
        s = t - (1.0 / T)
        g_s = self.gamma(s)
        loss_diff = 0.5 * T * np.expm1(g_s - g_t)[:, None, None] * loss_diff_mse
        return loss_diff

    def __call__(self, x, conditioning=None, mask=None):

        d_batch = x.shape[0]

        # 1. Reconstruction loss
        # Add noise and reconstruct
        f = self.encode(x, conditioning)
        loss_recon = self.recon_loss(x, f, conditioning)

        # 2. Latent loss
        # KL z1 with N(0,1) prior
        loss_klz = self.latent_loss(f)

        # 3. Diffusion loss
        # Sample time steps
        rng1 = self.make_rng("sample")
        if self.antithetic_time_sampling:
            t0 = jax.random.uniform(rng1)
            t = np.mod(t0 + np.arange(0.0, 1.0, step=1.0 / d_batch), 1.0)
        else:
            t = jax.random.uniform(rng1, shape=(d_batch,))

        # Discretize time steps if we're working with discrete time
        T = self.timesteps
        t = np.ceil(t * T) / T

        cond = self.embed(conditioning)
        loss_diff = self.diffusion_loss(t, f, cond, mask)

        return (loss_diff, loss_klz, loss_recon)

    def embed(self, conditioning):
        """Embed the conditioning vector, optionally including embedding a class assumed to be the first element of the vector."""

        # If
        if self.n_classes > 0 and conditioning.shape[-1] > 1:
            classes, conditioning = conditioning[..., 0].astype(np.int32), conditioning[..., 1:]
            class_embedding, context_embedding = self.embedding_class(classes), self.embedding_context(conditioning)
            return class_embedding + context_embedding
        elif self.n_classes > 0 and conditioning.shape[-1] == 1:
            classes = conditioning[..., 0].astype(np.int32)
            class_embedding = self.embedding_class(classes)
            return class_embedding
        elif self.n_classes == 0 and conditioning is not None:
            context_embedding = self.embedding_context(conditioning)
            return context_embedding
        else:  # If no conditioning
            return None

    def encode(self, x, conditioning=None):
        """Encode an image x."""
        if conditioning is not None:
            cond = self.embed(conditioning)
        else:
            cond = None
        return self.encoder(x, cond)

    def decode(self, z0, conditioning=None):
        """Decode a latent sample z0."""
        if conditioning is not None:
            cond = self.embed(conditioning)
        else:
            cond = None
        return self.decoder(z0, cond)

    def sample_step(self, rng, i, T, z_t, conditioning=None, mask=None):
        """Sample a single step of the diffusion process."""
        rng_body = jax.random.fold_in(rng, i)
        eps = jax.random.normal(rng_body, z_t.shape)
        t = (T - i) / T
        s = (T - i - 1) / T

        g_s = self.gamma(s)
        g_t = self.gamma(t)

        cond = self.embed(conditioning)

        eps_hat_cond = self.score_model(z_t, g_t * np.ones((z_t.shape[0],), z_t.dtype), cond, mask)

        a = nn.sigmoid(g_s)
        b = nn.sigmoid(g_t)
        c = -np.expm1(g_t - g_s)
        sigma_t = np.sqrt(sigma2(g_t))
        z_s = np.sqrt(a / b) * (z_t - sigma_t * c * eps_hat_cond) + np.sqrt((1.0 - a) * c) * eps

        return z_s