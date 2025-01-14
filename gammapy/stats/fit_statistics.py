# Licensed under a 3-clause BSD style license - see LICENSE.rst
"""Common fit statistics used in gamma-ray astronomy.

see :ref:`fit-statistics`
"""
import numpy as np

__all__ = ["cash", "cstat", "wstat", "get_wstat_mu_bkg", "get_wstat_gof_terms"]

N_ON_MIN = 1e-25


def cash(n_on, mu_on):
    r"""Cash statistic, for Poisson data.

    The Cash statistic is defined as:

    .. math::
        C = 2 \left( \mu_{on} - n_{on} \log \mu_{on} \right)

    and :math:`C = 0` where :math:`\mu <= 0`.
    For more information see :ref:`fit-statistics`

    Parameters
    ----------
    n_on : array_like
        Observed counts
    mu_on : array_like
        Expected counts

    Returns
    -------
    stat : ndarray
        Statistic per bin

    References
    ----------
    * `Sherpa statistics page section on the Cash statistic
      <http://cxc.cfa.harvard.edu/sherpa/statistics/#cash>`_
    * `Sherpa help page on the Cash statistic
      <http://cxc.harvard.edu/sherpa/ahelp/cash.html>`_
    * `Cash 1979, ApJ 228, 939
      <https://ui.adsabs.harvard.edu/abs/1979ApJ...228..939C>`_
    """
    n_on = np.asanyarray(n_on)
    mu_on = np.asanyarray(mu_on)

    # suppress zero division warnings, they are corrected below
    with np.errstate(divide="ignore", invalid="ignore"):
        stat = 2 * (mu_on - n_on * np.log(mu_on))
        stat = np.where(mu_on > 0, stat, 0)
    return stat


def cstat(n_on, mu_on, n_on_min=N_ON_MIN):
    r"""C statistic, for Poisson data.

    The C statistic is defined as

    .. math::
        C = 2 \left[ \mu_{on} - n_{on} + n_{on}
            (\log(n_{on}) - log(\mu_{on}) \right]

    and :math:`C = 0` where :math:`\mu_{on} <= 0`.

    ``n_on_min`` handles the case where ``n_on`` is 0 or less and
    the log cannot be taken.
    For more information see :ref:`fit-statistics`

    Parameters
    ----------
    n_on : array_like
        Observed counts
    mu_on : array_like
        Expected counts
    n_on_min : array_like
        ``n_on`` = ``n_on_min`` where ``n_on`` <= ``n_on_min.``

    Returns
    -------
    stat : ndarray
        Statistic per bin

    References
    ----------
    * `Sherpa stats page section on the C statistic
      <http://cxc.cfa.harvard.edu/sherpa/statistics/#cstat>`_
    * `Sherpa help page on the C statistic
      <http://cxc.harvard.edu/sherpa/ahelp/cash.html>`_
    * `Cash 1979, ApJ 228, 939
      <https://ui.adsabs.harvard.edu/abs/1979ApJ...228..939C>`_
    """
    n_on = np.asanyarray(n_on, dtype=np.float64)
    mu_on = np.asanyarray(mu_on, dtype=np.float64)
    n_on_min = np.asanyarray(n_on_min, dtype=np.float64)

    n_on = np.where(n_on <= n_on_min, n_on_min, n_on)

    term1 = np.log(n_on) - np.log(mu_on)
    stat = 2 * (mu_on - n_on + n_on * term1)
    stat = np.where(mu_on > 0, stat, 0)

    return stat


def wstat(n_on, n_off, alpha, mu_sig, mu_bkg=None, extra_terms=True):
    r"""W statistic, for Poisson data with Poisson background.

    For a definition of WStat see :ref:`wstat`. If ``mu_bkg`` is not provided
    it will be calculated according to the profile likelihood formula.

    Parameters
    ----------
    n_on : array_like
        Total observed counts
    n_off : array_like
        Total observed background counts
    alpha : array_like
        Exposure ratio between on and off region
    mu_sig : array_like
        Signal expected counts
    mu_bkg : array_like, optional
        Background expected counts
    extra_terms : bool, optional
        Add model independent terms to convert stat into goodness-of-fit
        parameter, default: True

    Returns
    -------
    stat : ndarray
        Statistic per bin

    References
    ----------
    * `Habilitation M. de Naurois, p. 141
      <http://inspirehep.net/record/1122589/files/these_short.pdf>`_
    * `XSPEC page on Poisson data with Poisson background
      <https://heasarc.nasa.gov/xanadu/xspec/manual/XSappendixStatistics.html>`_
    """
    # Note: This is equivalent to what's defined on the XSPEC page under the
    # following assumptions
    # t_s * m_i = mu_sig
    # t_b * m_b = mu_bkg
    # t_s / t_b = alpha

    n_on = np.atleast_1d(np.asanyarray(n_on, dtype=np.float64))
    n_off = np.atleast_1d(np.asanyarray(n_off, dtype=np.float64))
    alpha = np.atleast_1d(np.asanyarray(alpha, dtype=np.float64))
    mu_sig = np.atleast_1d(np.asanyarray(mu_sig, dtype=np.float64))

    if mu_bkg is None:
        mu_bkg = get_wstat_mu_bkg(n_on, n_off, alpha, mu_sig)

    term1 = mu_sig + (1 + alpha) * mu_bkg

    # suppress zero division warnings, they are corrected below
    with np.errstate(divide="ignore", invalid="ignore"):
        # This is a false positive error from pylint
        # See https://github.com/PyCQA/pylint/issues/2436
        term2_ = -n_on * np.log(
            mu_sig + alpha * mu_bkg
        )  # pylint:disable=invalid-unary-operand-type
    # Handle n_on == 0
    condition = n_on == 0
    term2 = np.where(condition, 0, term2_)

    # suppress zero division warnings, they are corrected below
    with np.errstate(divide="ignore", invalid="ignore"):
        # This is a false positive error from pylint
        # See https://github.com/PyCQA/pylint/issues/2436
        term3_ = -n_off * np.log(mu_bkg)  # pylint:disable=invalid-unary-operand-type
    # Handle n_off == 0
    condition = n_off == 0
    term3 = np.where(condition, 0, term3_)

    stat = 2 * (term1 + term2 + term3)

    if extra_terms:
        stat += get_wstat_gof_terms(n_on, n_off)

    return stat


def get_wstat_mu_bkg(n_on, n_off, alpha, mu_sig):
    """Background estimate ``mu_bkg`` for WSTAT.

    See :ref:`wstat`.
    """
    n_on = np.atleast_1d(np.asanyarray(n_on, dtype=np.float64))
    n_off = np.atleast_1d(np.asanyarray(n_off, dtype=np.float64))
    alpha = np.atleast_1d(np.asanyarray(alpha, dtype=np.float64))
    mu_sig = np.atleast_1d(np.asanyarray(mu_sig, dtype=np.float64))

    # NOTE: Corner cases in the docs are all handled correcty by this formula
    C = alpha * (n_on + n_off) - (1 + alpha) * mu_sig
    D = np.sqrt(C ** 2 + 4 * alpha * (alpha + 1) * n_off * mu_sig)
    mu_bkg = (C + D) / (2 * alpha * (alpha + 1))

    return mu_bkg


def get_wstat_gof_terms(n_on, n_off):
    """Goodness of fit terms for WSTAT.

    See :ref:`wstat`.
    """
    term = np.zeros(len(n_on))

    # suppress zero division warnings, they are corrected below
    with np.errstate(divide="ignore", invalid="ignore"):
        term1 = -n_on * (1 - np.log(n_on))
        term2 = -n_off * (1 - np.log(n_off))

    term += np.where(n_on == 0, 0, term1)
    term += np.where(n_off == 0, 0, term2)

    return 2 * term
