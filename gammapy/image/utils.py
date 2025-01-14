# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""Image utility functions"""
import functools
import logging
import multiprocessing
import numpy as np
import scipy.ndimage
import scipy.signal
from astropy.convolution import Gaussian2DKernel

__all__ = ["scale_cube"]

log = logging.getLogger(__name__)


def _fftconvolve_wrap(kernel, data):
    # wrap gaussian filter as a special case, because the gain in
    # performance is factor ~100
    if isinstance(kernel, Gaussian2DKernel):
        width = kernel.model.x_stddev.value
        norm = kernel.array.sum()
        return norm * scipy.ndimage.gaussian_filter(data, width)
    else:
        return scipy.signal.fftconvolve(data, kernel.array, mode="same")


def scale_cube(data, kernels, parallel=True):
    """
    Compute scale space cube.

    Compute scale space cube by convolving the data with a set of kernels and
    stack the resulting images along the third axis.

    Parameters
    ----------
    data : `~numpy.ndarray`
        Input data.
    kernels: list of `~astropy.convolution.Kernel`
        List of convolution kernels.
    parallel : bool
        Whether to use multiprocessing.

    Returns
    -------
    cube : `~numpy.ndarray`
        Array of the shape (len(kernels), data.shape)
    """
    wrap = functools.partial(_fftconvolve_wrap, data=data)

    if parallel:
        pool = multiprocessing.Pool()
        result = pool.map(wrap, kernels)
        pool.close()
        pool.join()
    else:
        result = map(wrap, kernels)
    return np.dstack(result)
