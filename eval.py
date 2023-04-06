import sys

sys.path.append("./")
sys.path.append("../")

from typing import List, Dict
from jax import random
import jax.numpy as np
import numpy as onp

import wandb
import matplotlib.pyplot as plt
from pycorr import TwoPointCorrelationFunction
from models.diffusion_utils import generate
from cosmo_utils.knn import get_CDFkNN

colors = [
    "lightseagreen",
    "mediumorchid",
    "salmon",
    "royalblue",
    "rosybrown",
]


def plot_pointclouds_3D(
    generated_samples: np.array, true_samples: np.array, idx_to_plot: int = 0
) -> plt.figure:
    """Plot pointcloud in three dimensions

    Args:
        generated_samples (np.array): samples generated by the model
        true_samples (np.array): true samples
        idx_to_plot (int, optional): idx to plot. Defaults to 0.

    Returns:
        plt.figure: figure
    """
    s = 4
    alpha = 0.5
    color = "firebrick"
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(20, 12), subplot_kw={"projection": "3d"}
    )
    ax1.scatter(
        generated_samples[idx_to_plot, :, 0],
        generated_samples[idx_to_plot, :, 1],
        generated_samples[idx_to_plot, :, 2],
        alpha=alpha,
        s=s,
        color=color,
    )
    ax1.set_title("Gen")
    ax1.set_xlabel("x")
    ax1.set_ylabel("y")
    ax1.set_zlabel("z")

    ax2.scatter(
        true_samples[idx_to_plot, :, 0],
        true_samples[idx_to_plot, :, 1],
        true_samples[idx_to_plot, :, 2],
        alpha=alpha,
        s=s,
        color=color,
    )
    ax1.set_title("Gen")
    ax1.set_xlabel("x")
    ax1.set_ylabel("y")
    ax1.set_zlabel("z")
    return fig


def plot_pointclouds_2D(
    generated_samples: np.array, true_samples: np.array, idx_to_plot: int = 0
):
    """Plot pointcloud in two dimensions

    Args:
        generated_samples (np.array): samples generated by the model
        true_samples (np.array): true samples
        idx_to_plot (int, optional): idx to plot. Defaults to 0.

    Returns:
        plt.figure: figure
    """
    s = 4
    alpha = 0.5
    color = "firebrick"
    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=(20, 12),
    )
    ax1.scatter(
        generated_samples[idx_to_plot, :, 0],
        generated_samples[idx_to_plot, :, 1],
        alpha=alpha,
        s=s,
        color=color,
    )
    ax1.set_title("Gen")
    ax1.set_xlabel("x")
    ax1.set_ylabel("y")

    ax2.scatter(
        true_samples[idx_to_plot, :, 0],
        true_samples[idx_to_plot, :, 1],
        alpha=alpha,
        s=s,
        color=color,
    )
    ax1.set_title("Gen")
    ax1.set_xlabel("x")
    ax1.set_ylabel("y")
    return fig


def plot_knns(
    generated_samples: np.array,
    true_samples: np.array,
    conditioning: np.array,
    boxsize: float = 1000.0,
    idx_to_plot: List[int] = [0, 1, 2],
) -> plt.figure:
    """plot nearest neighbour statistics

    Args:
        generated_samples (np.array): samples generated by the model
        true_samples (np.array): true samples
        conditioning (np.array): conditioning per sample
        boxsize (float, optional): size of the simulation box. Defaults to 1000.0.
        idx_to_plot (List[int], optional): idx to plot. Defaults to [0, 1, 2].

    Returns:
        plt.figure: figure
    """
    r_bins = np.linspace(0.5, 120.0, 60)
    k_bins = [1, 5, 9]
    key = random.PRNGKey(0)
    random_points = boxsize * random.uniform(
        key,
        shape=(len(true_samples[0]) * 10, 3),
    )
    fig, _ = plt.subplots()
    for i, idx in enumerate(idx_to_plot):
        sampled_knn = get_CDFkNN(
            r_bins=r_bins,
            pos=generated_samples[idx][..., :3],
            random_pos=random_points,
            boxsize=boxsize,
            k=k_bins,
        )
        true_knn = get_CDFkNN(
            r_bins=r_bins,
            pos=true_samples[idx][..., :3],
            random_pos=random_points,
            boxsize=boxsize,
            k=k_bins,
        )

        color = plt.rcParams["axes.prop_cycle"].by_key()["color"][i]
        for k in range(len(k_bins)):
            c = plt.plot(
                r_bins,
                true_knn[k],
                label=rf"$\Omega_m={conditioning[i][0]:.2f} \,\,\sigma_8={conditioning[i][-1]:.2f}$"
                if k == 1
                else None,
                ls="-",
                alpha=0.75,
                lw=2,
                color=color,
            )
            plt.plot(
                r_bins,
                sampled_knn[k],
                color=color,
                ls="--",
                alpha=0.75,
                lw=2,
            )
    plt.legend(
        fontsize=12,
        bbox_to_anchor=(0, 1.02, 1, 0.2),
        loc="lower left",
        mode="expand",
    )
    plt.text(
        25,
        0.5,
        f"k={k_bins[0]}",
        rotation=65,
    )
    plt.text(
        52,
        0.5,
        f"k={k_bins[1]}",
        rotation=65,
    )
    plt.text(
        66,
        0.5,
        f"k={k_bins[2]}",
        rotation=65,
    )
    plt.ylabel("CDF")
    plt.xlabel("r [Mpc/h]")
    return fig


def compute_2pcf(
    sample: np.array,
    boxsize: float,
    r_bins: np.array,
) -> np.array:
    """Get the monopole of the two point correlation function

    Args:
        sample (np.array): positions
        boxsize (float): size of the box
        r_bins (np.array): bins in pair separation

    Returns:
        np.array: monopole of the two point correlation function
    """
    mu_bins = np.linspace(-1, 1, 201)
    return TwoPointCorrelationFunction(
        "smu",
        edges=(onp.array(r_bins), onp.array(mu_bins)),
        data_positions1=onp.array(sample).T,
        engine="corrfunc",
        n_threads=2,
        boxsize=boxsize,
        los="z",
    )(ells=[0])[0]


def compute_2pcf_rsd(
    positions: np.array,
    velocities: np.array,
    omega_matter: float,
    boxsize: float,
    r_bins: np.array,
    redshift: float = 0.5,
) -> np.array:
    """Get the monopole of the two point correlation function

    Args:
        sample (np.array): positions
        boxsize (float): size of the box
        r_bins (np.array): bins in pair separation

    Returns:
        np.array: monopole of the two point correlation function
    """
    omega_l = 1 - omega_matter
    H_0 = 100.0
    az = 1 / (1 + redshift)
    Hz = H_0 * np.sqrt(omega_matter * (1 + redshift) ** 3 + omega_l)
    z_rsd = positions[..., -1] + velocities[..., -1] / (Hz * az)
    z_rsd %= boxsize
    rsd_positions = positions.copy()
    rsd_positions[..., -1] = z_rsd
    mu_bins = np.linspace(-1, 1, 201)
    return TwoPointCorrelationFunction(
        "smu",
        edges=(onp.array(r_bins), onp.array(mu_bins)),
        data_positions1=onp.array(rsd_positions).T,
        engine="corrfunc",
        n_threads=2,
        boxsize=boxsize,
        los="z",
    )(ells=[0, 2])


def plot_2pcf(
    generated_samples: np.array, true_samples: np.array, boxsize: float
) -> plt.figure:
    """Plot the two point correlation function

    Args:
        generated_samples (np.array): samples generated by the model
        true_samples (np.array): true samples
        boxsize (float): size of the box

    Returns:
        plt.figure: figure
    """
    generated_2pcfs, true_2pcfs = [], []
    r_bins = np.linspace(0.5, 120.0, 60)
    r = 0.5 * (r_bins[1:] + r_bins[:-1])
    for idx in range(len(generated_samples)):
        generated_2pcfs.append(
            compute_2pcf(generated_samples[idx][..., :3], boxsize, r_bins)
        )
        true_2pcfs.append(compute_2pcf(true_samples[idx][..., :3], boxsize, r_bins))

    fig, _ = plt.subplots()
    c = plt.loglog(r, onp.mean(true_2pcfs, axis=0), label="N-body")
    plt.plot(
        r,
        (onp.mean(true_2pcfs, axis=0) - onp.std(true_2pcfs, axis=0)),
        alpha=0.5,
        color=c[0].get_color(),
        linestyle="dashed",
    )
    plt.plot(
        r,
        (onp.mean(true_2pcfs, axis=0) + onp.std(true_2pcfs, axis=0)),
        alpha=0.5,
        color=c[0].get_color(),
        linestyle="dashed",
    )

    # fill_between somehow doesnt work with wandb :(
    # plt.fill_between(
    #    r,
    #    (onp.mean(true_2pcfs, axis=0) - onp.std(true_2pcfs,axis=0)),
    #    (onp.mean(true_2pcfs, axis=0) + onp.std(true_2pcfs,axis=0)),
    #    alpha=0.5,
    #    color=c[0].get_color(),
    # )
    c = plt.plot(r, onp.mean(generated_2pcfs, axis=0), label="Diffusion")
    plt.plot(
        r,
        (onp.mean(generated_2pcfs, axis=0) - onp.std(generated_2pcfs, axis=0)),
        alpha=0.5,
        color=c[0].get_color(),
        linestyle="dashed",
    )
    plt.plot(
        r,
        (onp.mean(generated_2pcfs, axis=0) + onp.std(generated_2pcfs, axis=0)),
        alpha=0.5,
        color=c[0].get_color(),
        linestyle="dashed",
    )
    # plt.fill_between(
    #    r,
    #    (onp.mean(generated_2pcfs, axis=0) - onp.std(generated_2pcfs,axis=0)),
    #    (onp.mean(generated_2pcfs, axis=0) + onp.std(generated_2pcfs,axis=0)),
    #    alpha=0.5,
    #    color=c[0].get_color(),
    # )
    plt.ylabel("2PCF")
    plt.xlabel("r [Mpc/h]")
    plt.legend(fontsize=8)
    return fig


def plot_velocity_histograms(
    generated_velocities: np.array,
    true_velocities: np.array,
    idx_to_plot: List[int],
)->plt.figure:
    """ plot histograms of velocity modulus

    Args:
        generated_velocities (np.array): generated 3D velociteis 
        true_velocities (np.array): true 3D velocities 
        idx_to_plot (List[int]): idx to plot 

    Returns:
        plt.Figure: figure vel hist 
    """
    generated_mod = onp.sqrt(onp.sum(generated_velocities**2, axis=-1))
    true_mod = onp.sqrt(onp.sum(true_velocities**2, axis=-1))
    fig, _ = plt.subplots(figsize=(15, 5))
    offset = 0
    for i, idx in enumerate(idx_to_plot):
        true_hist, bin_edges = np.histogram(
           true_mod[idx], bins= 50, 
        )
        generated_hist, bin_edges = np.histogram(
           generated_mod[idx], bins= bin_edges, 
        )
        bin_centres = 0.5*(bin_edges[1:] + bin_edges[:-1])
        plt.plot(
            bin_centres + offset,
            true_hist,
            label="N-body" if i == 0 else None,
            color=colors[i],
        )
        plt.plot(
            bin_centres + offset,
            generated_hist,
            label="Diffusion" if i == 0 else None,
            linestyle='dashed',
            color=colors[i],
        )
        offset += onp.max(true_mod)
    plt.legend()
    plt.xlabel("|v| + offset [km/s]")
    plt.ylabel("PDF")
    return fig


def plot_hmf(
    generated_masses: np.array,
    true_masses: np.array,
    idx_to_plot: List[int],
)->plt.figure:
    """ plot halo mass functions

    Args:
        generated_masses (np.array): generated masses 
        true_masses (np.array): true masses 
        idx_to_plot (List[int]): idx to plot 

    Returns:
        plt.Figure: hmf figure 
    """
    fig, _ = plt.subplots()
    for i, idx in enumerate(idx_to_plot):
        true_hist, bin_edges = np.histogram(
           true_masses[idx], bins= 50, 
        )
        generated_hist, bin_edges = np.histogram(
           generated_masses[idx], bins= bin_edges, 
        )
        bin_centres = 0.5*(bin_edges[1:] + bin_edges[:-1])
        plt.semilogy(
            bin_centres,
            true_hist,
            label="N-body" if i == 0 else None,
            color=colors[i],
        )
        plt.semilogy(
            bin_centres,
            generated_hist,
            label="Diffusion" if i == 0 else None,
            color=colors[i],
            linestyle='dashed',
        )

    plt.legend()
    plt.xlabel("log Halo Mass")
    plt.ylabel("PDF")
    return fig


def plot_2pcf_rsd(
    generated_positions: np.array,
    true_positions: np.array,
    generated_velocities: np.array,
    true_velocities: np.array,
    conditioning: np.array,
    boxsize: float,
) -> plt.figure:
    """ plot 2pcf in redshift space 

    Args:
        generated_positions (np.array): generated 3D positions 
        true_positions (np.array): true 3D positions 
        generated_velocities (np.array): generated 3D velociteis 
        true_velocities (np.array): true 3D velocities 
        conditioning (np.array): conditioning (cosmological params) 
        boxsize (float): boxsize 

    Returns:
        plt.figure: fig with monopole and quadrupole 
    """
    generated_2pcfs, true_2pcfs = [], []
    r_bins = np.linspace(0.5, 120.0, 60)
    r = 0.5 * (r_bins[1:] + r_bins[:-1])
    for idx in range(len(generated_positions)):
        generated_2pcfs.append(
            compute_2pcf_rsd(
                positions=generated_positions[idx],
                velocities=generated_velocities[idx],
                omega_matter=conditioning[idx, 0],
                boxsize=boxsize,
                r_bins=r_bins,
            )
        )
        true_2pcfs.append(
            compute_2pcf_rsd(
                positions=true_positions[idx],
                velocities=true_velocities[idx],
                omega_matter=conditioning[idx, 0],
                boxsize=boxsize,
                r_bins=r_bins,
            )
        )
    fig, ax = plt.subplots(nrows=2, figsize=(8, 12))
    true_2pcfs = onp.array(true_2pcfs)
    true_2pcfs[:, 1, ...] = true_2pcfs[:, 1, ...] * r**2
    generated_2pcfs = onp.array(generated_2pcfs)
    generated_2pcfs[:, 1, ...] = generated_2pcfs[:, 1, ...] * r**2
    for i in range(2):
        if i == 0:
            c = ax[i].loglog(r, onp.mean(true_2pcfs, axis=0)[i], label="N-body")
        else:
            c = ax[i].semilogx(r, onp.mean(true_2pcfs, axis=0)[i], label="N-body")
        ax[i].plot(
            r,
            (onp.mean(true_2pcfs, axis=0) - onp.std(true_2pcfs, axis=0))[i],
            color=c[0].get_color(),
            linestyle="dashed",
        )
        ax[i].plot(
            r,
            (onp.mean(true_2pcfs, axis=0) + onp.std(true_2pcfs, axis=0))[i],
            color=c[0].get_color(),
            linestyle="dashed",
        )

        c = ax[i].plot(r, onp.mean(generated_2pcfs, axis=0)[i], label="Diffusion")
        ax[i].plot(
            r,
            (onp.mean(generated_2pcfs, axis=0) - onp.std(generated_2pcfs, axis=0))[i],
            color=c[0].get_color(),
            linestyle="dashed",
        )
        ax[i].plot(
            r,
            (onp.mean(generated_2pcfs, axis=0) + onp.std(generated_2pcfs, axis=0))[i],
            color=c[0].get_color(),
            linestyle="dashed",
        )
    ax[0].set_ylabel("Monopole")
    ax[1].set_ylabel("r^2 Quadrupole")
    plt.xlabel("r [Mpc/h]")
    plt.legend(fontsize=8)
    return fig


def eval_generation(
    vdm,
    pstate,
    rng,
    n_samples: int,
    n_particles: int,
    true_samples: np.array,
    conditioning: np.array,
    mask: np.array,
    norm_dict: Dict,
    steps: int = 1000,
    boxsize: float = 1000.0,
):
    """Evaluate the model on a small subset and log figures and log figures and log figures and log figures

    Args:
        vdm (_type_): diffusion model
        pstate (_type_): model weights
        rng (_type_): random key
        n_samples (int): number of samples to generate
        n_particles (int): number of particles to sample
        true_samples (np.array): true samples
        conditioning (np.array): conditioning of the true samples
        mask (np.array): mask
        norm_dict (Dict): dictionariy with mean and std of the true samples, used to normalize the data
        steps (int, optional): number of steps to sample in diffusion. Defaults to 100.
        boxsize (float, optional): size of the simulation box. Defaults to 1000.0.
    """
    generated_samples = generate(
        vdm,
        pstate.params,
        rng,
        (n_samples, n_particles),
        conditioning=conditioning,
        mask=mask,
        steps=steps,
    )
    generated_samples = generated_samples.mean()
    generated_samples = generated_samples * norm_dict["std"] + norm_dict["mean"]
    # make sure generated samples are inside boxsize
    generated_samples = generated_samples.at[..., :3].set(
        generated_samples[..., :3] % boxsize
    )
    true_samples = true_samples * norm_dict["std"] + norm_dict["mean"]
    true_positions = true_samples[..., :3]
    generated_positions = generated_samples[..., :3]
    if generated_samples.shape[-1] > 3:
        generated_velocities = generated_samples[..., 3:6]
        generated_masses = generated_samples[..., -1]
        true_velocities = true_samples[..., 3:6]
        if generated_samples.shape[-1] > 6:
            true_masses = true_samples[..., -1]
        else:
            generated_masses = None
            true_masses = None
    else:
        generated_velocities = None
        generated_masses = None
        true_velocities = None
        true_masses = None
    fig = plot_pointclouds_2D(
        generated_samples=generated_positions, true_samples=true_positions
    )
    wandb.log({"eval/pointcloud": fig})

    fig = plot_knns(
        generated_samples=generated_positions,
        true_samples=true_positions,
        conditioning=conditioning,
        boxsize=boxsize,
        idx_to_plot=[0, 1, 2],
    )
    wandb.log({"eval/knn": fig})

    fig = plot_2pcf(
        generated_samples=generated_positions,
        true_samples=true_positions,
        boxsize=boxsize,
    )
    wandb.log({"eval/2pcf": fig})

    if generated_velocities is not None:
        fig = plot_velocity_histograms(
            generated_velocities=generated_velocities,
            true_velocities=true_velocities,
            idx_to_plot=[0, 1, 2],
        )
        wandb.log({"eval/vels": fig})
        fig = plot_2pcf_rsd(
            generated_positions=onp.array(generated_positions),
            true_positions=onp.array(true_positions),
            generated_velocities=onp.array(generated_velocities),
            true_velocities=onp.array(true_velocities),
            conditioning=onp.array(conditioning),
            boxsize=boxsize,
        )
        wandb.log({"eval/2pcf_rsd": fig})

    if generated_masses is not None:
        fig = plot_hmf(
            generated_masses=generated_masses,
            true_masses=true_masses,
            idx_to_plot=[0, 1, 2],
        )
        wandb.log({"eval/mass": fig})
