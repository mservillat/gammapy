# Licensed under a 3-clause BSD style license - see LICENSE.rst
import logging
import numpy as np
import scipy.integrate
import scipy.special
import astropy.units as u
from astropy.coordinates import Angle, Latitude, Longitude, SkyCoord
from astropy.coordinates.angle_utilities import angular_separation, position_angle
from gammapy.maps import Map
from gammapy.utils.fitting import Model, Parameter

__all__ = [
    "SkySpatialModel",
    "SkyPointSource",
    "SkyGaussian",
    "SkyGaussianElongated",
    "SkyDisk",
    "SkyEllipse",
    "SkyShell",
    "SkyDiffuseConstant",
    "SkyDiffuseMap",
]


log = logging.getLogger(__name__)

EDGE_WIDTH_95 = 2.326174307353347


def smooth_edge(x, width):
    value = (x / width).to_value("")
    return 0.5 * (1 - scipy.special.erf(value * EDGE_WIDTH_95))


class SkySpatialModel(Model):
    """Sky spatial model base class."""

    def __call__(self, lon, lat):
        """Call evaluate method"""
        kwargs = dict()
        for par in self.parameters.parameters:
            kwargs[par.name] = par.quantity

        return self.evaluate(lon, lat, **kwargs)

    @property
    def position(self):
        """Spatial model center position"""
        try:
            lon = self.lon_0.quantity
            lat = self.lat_0.quantity
            return SkyCoord(lon, lat, frame=self.frame)
        except IndexError:
            raise ValueError("Model does not have a defined center position")


class SkyPointSource(SkySpatialModel):
    r"""Point Source.

    .. math:: \phi(lon, lat) = \delta{(lon - lon_0, lat - lat_0)}

    Parameters
    ----------
    lon_0 : `~astropy.coordinates.Longitude`
        :math:`lon_0`
    lat_0 : `~astropy.coordinates.Latitude`
        :math:`lat_0`
    frame : {"galactic", "icrs"}
        Coordinate frame of `lon_0` and `lat_0`.
    """

    __slots__ = ["frame", "lon_0", "lat_0"]

    def __init__(self, lon_0, lat_0, frame="galactic"):
        self.frame = frame
        self.lon_0 = Parameter(
            "lon_0", Longitude(lon_0).wrap_at("180d"), min=-180, max=180
        )
        self.lat_0 = Parameter("lat_0", Latitude(lat_0), min=-90, max=90)

        super().__init__([self.lon_0, self.lat_0])

    @property
    def evaluation_radius(self):
        """Evaluation radius (`~astropy.coordinates.Angle`).

        Set as zero degrees.
        """
        return 0 * u.deg

    @staticmethod
    def evaluate(lon, lat, lon_0, lat_0):
        """Evaluate model."""
        wrapval = lon_0 + 180 * u.deg
        lon = Angle(lon).wrap_at(wrapval)

        _, grad_lon = np.gradient(lon)
        grad_lat, _ = np.gradient(lat)
        lon_diff = np.abs((lon - lon_0) / grad_lon)
        lat_diff = np.abs((lat - lat_0) / grad_lat)

        lon_val = np.select([lon_diff < 1], [1 - lon_diff], 0) / np.abs(grad_lon)
        lat_val = np.select([lat_diff < 1], [1 - lat_diff], 0) / np.abs(grad_lat)

        return lon_val * lat_val


class SkyGaussian(SkySpatialModel):
    r"""Two-dimensional symmetric Gaussian model.

    .. math::
        \phi(\text{lon}, \text{lat}) = N \times \exp\left\{-\frac{1}{2}
            \frac{1-\cos \theta}{1-\cos \sigma}\right\}\,,

    where :math:`\theta` is the sky separation to the model center.
    This angle is calculated on the celestial sphere using the function `angular.separation` defined in
    `astropy.coordinates.angle_utilities`. The Gaussian is normalized to 1 on
    the sphere:

    .. math::
        N = \frac{1}{4\pi a\left[1-\exp(-1/a)\right]}\,,\,\,\,\,
        a = 1-\cos \sigma\,.

    The normalization factor is in units of :math:`\text{sr}^{-1}`.
    In the limit of small :math:`\theta` and :math:`\sigma`, this definition
    reduces to the usual form:

    .. math::
        \phi(\text{lon}, \text{lat}) = \frac{1}{2\pi\sigma^2} \exp{\left(-\frac{1}{2}
            \frac{\theta^2}{\sigma^2}\right)}

    Parameters
    ----------
    lon_0 : `~astropy.coordinates.Longitude`
        :math:`\text{lon}_0`
    lat_0 : `~astropy.coordinates.Latitude`
        :math:`\text{lat}_0`
    sigma : `~astropy.coordinates.Angle`
        :math:`\sigma`
    frame : {"galactic", "icrs"}
        Coordinate frame of `lon_0` and `lat_0`.
    """

    __slots__ = ["frame", "lon_0", "lat_0", "sigma"]

    def __init__(self, lon_0, lat_0, sigma, frame="galactic"):
        self.frame = frame
        self.lon_0 = Parameter(
            "lon_0", Longitude(lon_0).wrap_at("180d"), min=-180, max=180
        )
        self.lat_0 = Parameter("lat_0", Latitude(lat_0), min=-90, max=90)
        self.sigma = Parameter("sigma", Angle(sigma), min=0)

        super().__init__([self.lon_0, self.lat_0, self.sigma])

    @property
    def evaluation_radius(self):
        r"""Evaluation radius (`~astropy.coordinates.Angle`).

        Set as :math:`5\sigma`.
        """
        return 5 * self.parameters["sigma"].quantity

    @staticmethod
    def evaluate(lon, lat, lon_0, lat_0, sigma):
        """Evaluate model."""
        sep = angular_separation(lon, lat, lon_0, lat_0)
        a = 1.0 - np.cos(sigma)
        norm = 1 / (4 * np.pi * a * (1.0 - np.exp(-1.0 / a)))
        exponent = -0.5 * ((1 - np.cos(sep)) / a)
        return u.Quantity(norm.value * np.exp(exponent).value, "sr-1", copy=False)


class SkyGaussianElongated(SkySpatialModel):
    r"""Two-dimensional elongated Gaussian model.

    .. math::
        \phi(\text{lon}, \text{lat}) = N \times \exp\left\{-\frac{1}{2}
            \frac{1-\cos(\theta)}{1-\cos\sigma_{eff}}\right\}\,,

    where :math:`\theta` is the sky separation to the model center.
    The effective radius of the Gaussian, used for the evaluation of the model, is:

    .. math::
        \sigma_{eff}(\text{lon}, \text{lat}) = \sqrt{
            (\sigma_M \sin(\Delta \phi))^2 +
            (\sigma_m \cos(\Delta \phi))^2
        },

    where :math:`\sigma_M` (:math:`\sigma_m`) is the major (minor) semiaxis of the Gaussian, and
    :math:`\Delta \phi` is the difference between `phi`, the position angle of the Gaussian, and the
    position angle of the evaluation point.

    **Caveat:** The model is normalized to 1 on the plane, i.e. in small angle approximation:
    :math:`N = 1/(2 \pi \sigma_M \sigma_m)`. This means that for huge elongated Gaussians on the sky
    this model is not correctly normalized. However, this approximation is perfectly acceptable for the more
    common case of models with modest dimensions: indeed, the error introduced by normalizing on the plane
    rather than on the sphere is below 0.1\% for Gaussians with radii smaller than ~ 5 deg.

    Parameters
    ----------
    lon_0 : `~astropy.coordinates.Longitude`
        :math:`\text{lon}_0`: `lon` coordinate for the center of the Gaussian.
    lat_0 : `~astropy.coordinates.Latitude`
        :math:`\text{lat}_0`: `lat` coordinate for the center of the Gaussian.
    sigma_semi_major : `~astropy.coordinates.Angle`
        Length of the major semiaxis of the Gaussian, in angular units.
    e : `float`
        Eccentricity of the Gaussian (:math:`0< e< 1`).
    phi : `~astropy.coordinates.Angle`
        Rotation angle :math:`\phi`: of the major semiaxis.
        Increases counter-clockwise from the North direction.
    frame : {"galactic", "icrs"}
        Coordinate frame of `lon_0` and `lat_0`.

    Examples
    --------
    .. plot::
        :include-source:

        import numpy as np
        import matplotlib.pyplot as plt
        import astropy.units as u
        from astropy.coordinates import Angle
        from gammapy.image.models import SkyGaussianElongated
        from gammapy.maps import Map, WcsGeom

        m_geom = WcsGeom.create(
            binsz=0.01, width=(5, 5), skydir=(2, 2), coordsys="GAL", proj="AIT"
        )
        phi = Angle("30 deg")
        model = SkyGaussianElongated("2 deg", "2 deg", "1 deg", 0.7, phi, frame="galactic")

        coords = m_geom.get_coord()
        lon = coords.lon * u.deg
        lat = coords.lat * u.deg
        vals = model(lon, lat)
        skymap = Map.from_geom(m_geom, data=vals.value)

        _, ax, _ = skymap.smooth("0.05 deg").plot()

        transform = ax.get_transform("galactic")
        ax.scatter(2, 2, transform=transform, s=20, edgecolor="red", facecolor="red")
        ax.text(1.5, 1.85, r"$(l_0, b_0)$", transform=transform, ha="center")
        ax.plot([2, 2 + np.sin(phi)], [2, 2 + np.cos(phi)], color="r", transform=transform)
        ax.vlines(x=2, color="r", linestyle="--", transform=transform, ymin=-5, ymax=5)
        ax.text(2.25, 2.45, r"$\phi$", transform=transform)
        ax.contour(skymap.data, cmap="coolwarm", levels=10, alpha=0.6)

        plt.show()
    """

    __slots__ = ["frame", "lon_0", "lat_0", "sigma_semi_major", "e", "phi"]

    def __init__(self, lon_0, lat_0, sigma_semi_major, e, phi, frame="galactic"):
        self.frame = frame
        self.lon_0 = Parameter(
            "lon_0", Longitude(lon_0).wrap_at("180d"), min=-180, max=180
        )
        self.lat_0 = Parameter("lat_0", Latitude(lat_0), min=-90, max=90)
        self.sigma_semi_major = Parameter("sigma_semi_major", Angle(sigma_semi_major))
        self.e = Parameter("e", e, min=0, max=1)
        self.phi = Parameter("phi", Angle(phi))

        super().__init__(
            [self.lon_0, self.lat_0, self.sigma_semi_major, self.e, self.phi]
        )

    @property
    def evaluation_radius(self):
        r"""Evaluation radius (`~astropy.coordinates.Angle`).

        Set as :math:`5\sigma`.
        """
        return 5 * self.parameters["sigma_semi_major"].quantity

    @staticmethod
    def evaluate(lon, lat, lon_0, lat_0, sigma_semi_major, e, phi):
        """Evaluate model."""
        sep = angular_separation(lon, lat, lon_0, lat_0)

        phi_0 = position_angle(lon_0, lat_0, lon, lat)
        d_phi = phi - phi_0
        sigma_semi_minor = Angle(sigma_semi_major * np.sqrt(1 - e ** 2))

        # Effective radius, used for model evaluation as in the symmetric case
        a2 = (sigma_semi_major * np.sin(d_phi)) ** 2
        b2 = (sigma_semi_minor * np.cos(d_phi)) ** 2
        denominator = np.sqrt(a2 + b2)
        sigma_eff = sigma_semi_major * sigma_semi_minor / denominator

        norm = 1 / (2 * np.pi * sigma_semi_major * sigma_semi_minor)

        a = 1.0 - np.cos(sigma_eff)
        exponent = -0.5 * ((1 - np.cos(sep)) / a)
        return u.Quantity(
            norm.to_value("sr-1") * np.exp(exponent).value, "sr-1", copy=False
        )


class SkyDisk(SkySpatialModel):
    r"""Constant radial disk model.

    .. math::
        \phi(lon, lat) = \frac{1}{2 \pi (1 - \cos{r_0}) } \cdot
                \begin{cases}
                    1 & \text{for } \theta \leq r_0 \\
                    0 & \text{for } \theta > r_0
                \end{cases}

    where :math:`\theta` is the sky separation. To improve fit convergence of the
    model, the sharp edges is smoothed using `~scipy.special.erf`.

    Parameters
    ----------
    lon_0 : `~astropy.coordinates.Longitude`
        :math:`lon_0`
    lat_0 : `~astropy.coordinates.Latitude`
        :math:`lat_0`
    r_0 : `~astropy.coordinates.Angle`
        :math:`r_0`
    edge : `~astropy.coordinates.Angle`
        Width of the edge. The width is defined as the range within the
        smooth edges of the model drops from 95% to 5% of its amplitude
        (see illustration below).
    frame : {"galactic", "icrs"}
        Coordinate frame of `lon_0` and `lat_0`.

    Examples
    --------
    Here is an illustration of the definition of the edge parameter:

    .. plot::
        :include-source:

        import matplotlib.pyplot as plt
        from astropy import units as u
        from gammapy.image.models import SkyDisk

        lons = np.linspace(0, 0.3, 500) * u.deg

        r_0 = 0.2 * u.deg
        edge = 0.1 * u.deg

        disk = SkyDisk(lon_0="0 deg", lat_0="0 deg", r_0=r_0, edge=edge)
        profile = disk(lons, 0 * u.deg)
        plt.plot(lons, profile / profile.max(), alpha=0.5)
        plt.xlabel("Radius (deg)")
        plt.ylabel("Profile (A.U.)")

        edge_min, edge_max = (r_0 - edge / 2.).value, (r_0 + edge / 2.).value
        plt.vlines([edge_min, edge_max], 0, 1, linestyles=["--"])
        plt.annotate("", xy=(edge_min, 0.5), xytext=(edge_min + edge.value, 0.5),
                     arrowprops=dict(arrowstyle="<->", lw=2))
        plt.text(0.2, 0.52, "Edge width", ha="center", size=12)
        plt.hlines([0.95], edge_min - 0.02, edge_min + 0.02, linestyles=["-"])
        plt.text(edge_min + 0.02, 0.95, "95%", size=12, va="center")
        plt.hlines([0.05], edge_max - 0.02, edge_max + 0.02, linestyles=["-"])
        plt.text(edge_max - 0.02, 0.05, "5%", size=12, va="center", ha="right")
        plt.show()
    """

    __slots__ = ["frame", "lon_0", "lat_0", "r_0"]

    def __init__(self, lon_0, lat_0, r_0, edge="0.01 deg", frame="galactic"):
        self.frame = frame
        self.lon_0 = Parameter(
            "lon_0", Longitude(lon_0).wrap_at("180d"), min=-180, max=180
        )
        self.lat_0 = Parameter("lat_0", Latitude(lat_0), min=-90, max=90)
        self.r_0 = Parameter("r_0", Angle(r_0))
        self.edge = Parameter("edge", Angle(edge), min=0.01, frozen=True)

        super().__init__([self.lon_0, self.lat_0, self.r_0, self.edge])

    @property
    def evaluation_radius(self):
        r"""Evaluation radius (`~astropy.coordinates.Angle`).

        Set to :math:`r_0`.
        """
        return self.parameters["r_0"].quantity

    @staticmethod
    def evaluate(lon, lat, lon_0, lat_0, r_0, edge):
        """Evaluate model."""
        sep = angular_separation(lon, lat, lon_0, lat_0)

        # Surface area of a spherical cap, see https://en.wikipedia.org/wiki/Spherical_cap
        norm = 1.0 / (2 * np.pi * (1 - np.cos(r_0)))

        in_disk = smooth_edge(sep - r_0, edge)
        return u.Quantity(norm.value * in_disk, "sr-1", copy=False)


class SkyEllipse(SkySpatialModel):
    r"""Constant elliptical model.

    .. math::
       \phi(\text{lon}, \text{lat}) =
                \begin{cases}
                    N & \text{for }  \,\,\,dist(F_1,P)+dist(F_2,P)\leq 2 a \\
                    0 & \text{otherwise }\,,
                \end{cases}

    where :math:`F_1` and :math:`F_2` represent the foci of the ellipse,
    :math:`P` is a generic point of coordinates :math:`(\text{lon}, \text{lat})`,
    :math:`a` is the major semiaxis of the ellipse and N is the model's
    normalization, in units of :math:`\text{sr}^{-1}`.

    The model is defined on the celestial sphere, with a normalization defined by:

    .. math::
        \int_{4\pi}\phi(\text{lon}, \text{lat}) \,d\Omega = 1\,.

    Parameters
    ----------
    lon_0 : `~astropy.coordinates.Longitude`
        :math:`\text{lon}_0`: `lon` coordinate for the center of the ellipse.
    lat_0 : `~astropy.coordinates.Latitude`
        :math:`\text{lat}_0`: `lat` coordinate for the center of the ellipse.
    semi_major : `~astropy.coordinates.Angle`
        :math:`a`: length of the major semiaxis, in angular units.
    e : `float`
        Eccentricity of the ellipse (:math:`0< e< 1`).
    phi : `~astropy.coordinates.Angle`
        Rotation angle :math:`\phi`: of the major semiaxis.
        Increases counter-clockwise from the North direction.
    edge : `~astropy.coordinates.Angle`
        Width of the edge. The width is defined as the range within the
        smooth edges of the model drops from 95% to 5% of its amplitude
        (see illustration for `SkyDisk`).
    frame : {"galactic", "icrs"}
        Coordinate frame of `lon_0` and `lat_0`.

    Examples
    --------
    .. plot::
        :include-source:

        import numpy as np
        import matplotlib.pyplot as plt
        import astropy.units as u
        from gammapy.image.models.core import SkyEllipse
        from gammapy.maps import Map, WcsGeom

        model = SkyEllipse("2 deg", "2 deg", "1 deg", 0.8, "30 deg", frame= "galactic")

        m_geom = WcsGeom.create(binsz=0.01, width=(3, 3), skydir=(2, 2), coordsys="GAL", proj="AIT")
        coords = m_geom.get_coord()
        lon = coords.lon * u.deg
        lat = coords.lat * u.deg
        vals = model(lon, lat)
        skymap = Map.from_geom(m_geom, data=vals.value)

        _, ax, _ = skymap.smooth("0.05 deg").plot()

        transform = ax.get_transform('galactic')
        ax.scatter(2, 2, transform=transform, s=20, edgecolor='red', facecolor='red')
        ax.text(1.7, 1.85, r"$(l_0, b_0)$", transform=transform, ha="center")
        ax.plot([2, 2 + np.sin(np.pi / 6)], [2, 2 + np.cos(np.pi / 6)], color="r", transform=transform)
        ax.vlines(x=2, color='r', linestyle='--', transform=transform, ymin=0, ymax=5)
        ax.text(2.15, 2.3, r"$\phi$", transform=transform);

        plt.show()
        """

    __slots__ = ["frame", "lon_0", "lat_0", "semi_major", "e", "phi", "_offset_by"]

    def __init__(
        self, lon_0, lat_0, semi_major, e, phi, edge="0.01 deg", frame="galactic"
    ):
        try:
            from astropy.coordinates.angle_utilities import offset_by

            self._offset_by = offset_by
        except ImportError:
            raise ImportError("The SkyEllipse model requires astropy>=3.1")

        self.frame = frame
        self.lon_0 = Parameter(
            "lon_0", Longitude(lon_0).wrap_at("180d"), min=-180, max=180
        )
        self.lat_0 = Parameter("lat_0", Latitude(lat_0), min=-90, max=90)
        self.semi_major = Parameter("semi_major", Angle(semi_major))
        self.e = Parameter("e", e, min=0, max=1)
        self.phi = Parameter("phi", Angle(phi))
        self.edge = Parameter("edge", Angle(edge), frozen=True, min=0.01)

        super().__init__(
            [self.lon_0, self.lat_0, self.semi_major, self.e, self.phi, self.edge]
        )

    @property
    def evaluation_radius(self):
        """Evaluation radius (`~astropy.coordinates.Angle`).

        Set to the length of the semi-major axis.
        """
        return self.parameters["semi_major"].quantity

    @staticmethod
    def compute_norm(semi_major, e):
        """Compute the normalization factor."""
        semi_minor = semi_major * np.sqrt(1 - e ** 2)

        def integral_fcn(x, a, b):
            A = 1 / np.sin(a) ** 2
            B = 1 / np.sin(b) ** 2
            C = A - B
            cs2 = np.cos(x) ** 2

            return 1 - np.sqrt(1 - 1 / (B + C * cs2))

        return (
            2
            * scipy.integrate.quad(
                lambda x: integral_fcn(x, semi_major, semi_minor), 0, np.pi
            )[0]
        ) ** -1

    def evaluate(self, lon, lat, lon_0, lat_0, semi_major, e, phi, edge):
        """Evaluate model."""
        # find the foci of the ellipse
        c = semi_major * e
        lon_1, lat_1 = self._offset_by(lon_0, lat_0, phi, c)
        lon_2, lat_2 = self._offset_by(lon_0, lat_0, 180 * u.deg + phi, c)

        sep_1 = angular_separation(lon, lat, lon_1, lat_1)
        sep_2 = angular_separation(lon, lat, lon_2, lat_2)

        in_ellipse = smooth_edge(sep_1 + sep_2 - 2 * semi_major, 2 * edge)

        norm = SkyEllipse.compute_norm(semi_major, e)
        return u.Quantity(norm * in_ellipse, "sr-1", copy=False)


class SkyShell(SkySpatialModel):
    r"""Shell model.

    .. math::
        \phi(lon, lat) = \frac{3}{2 \pi (r_{out}^3 - r_{in}^3)} \cdot
                \begin{cases}
                    \sqrt{r_{out}^2 - \theta^2} - \sqrt{r_{in}^2 - \theta^2} &
                                 \text{for } \theta \lt r_{in} \\
                    \sqrt{r_{out}^2 - \theta^2} &
                                 \text{for } r_{in} \leq \theta \lt r_{out} \\
                    0 & \text{for } \theta > r_{out}
                \end{cases}

    where :math:`\theta` is the sky separation and :math:`r_{\text{out}} = r_{\text{in}}` + width

    Note that the normalization is a small angle approximation,
    although that approximation is still very good even for 10 deg radius shells.

    Parameters
    ----------
    lon_0 : `~astropy.coordinates.Longitude`
        :math:`lon_0`
    lat_0 : `~astropy.coordinates.Latitude`
        :math:`lat_0`
    radius : `~astropy.coordinates.Angle`
        Inner radius, :math:`r_{in}`
    width : `~astropy.coordinates.Angle`
        Shell width
    frame : {"galactic", "icrs"}
        Coordinate frame of `lon_0` and `lat_0`.
    """

    __slots__ = ["frame", "lon_0", "lat_0", "radius", "width"]

    def __init__(self, lon_0, lat_0, radius, width, frame="galactic"):
        self.frame = frame
        self.lon_0 = Parameter(
            "lon_0", Longitude(lon_0).wrap_at("180d"), min=-180, max=180
        )
        self.lat_0 = Parameter("lat_0", Latitude(lat_0), min=-90, max=90)
        self.radius = Parameter("radius", Angle(radius))
        self.width = Parameter("width", Angle(width))

        super().__init__([self.lon_0, self.lat_0, self.radius, self.width])

    @property
    def evaluation_radius(self):
        r"""Evaluation radius (`~astropy.coordinates.Angle`).

        Set to :math:`r_\text{out}`.
        """
        return self.parameters["radius"].quantity + self.parameters["width"].quantity

    @staticmethod
    def evaluate(lon, lat, lon_0, lat_0, radius, width):
        """Evaluate model."""
        sep = angular_separation(lon, lat, lon_0, lat_0)
        radius_out = radius + width

        norm = 3 / (2 * np.pi * (radius_out ** 3 - radius ** 3))

        with np.errstate(invalid="ignore"):
            # np.where and np.select do not work with quantities, so we use the
            # workaround with indexing
            value = np.sqrt(radius_out ** 2 - sep ** 2)
            mask = [sep < radius]
            value[mask] = (value - np.sqrt(radius ** 2 - sep ** 2))[mask]
            value[sep > radius_out] = 0

        return norm * value


class SkyDiffuseConstant(SkySpatialModel):
    """Spatially constant (isotropic) spatial model.

    Parameters
    ----------
    value : `~astropy.units.Quantity`
        Value
    """

    __slots__ = ["value"]

    frame = None

    def __init__(self, value=1):
        self.value = Parameter("value", value)

        super().__init__([self.value])

    @property
    def evaluation_radius(self):
        """Evaluation radius (``None``)."""
        return None

    @staticmethod
    def evaluate(lon, lat, value):
        """Evaluate model."""
        return value


class SkyDiffuseMap(SkySpatialModel):
    """Spatial sky map template model (2D).

    This is for a 2D image. Use `~gammapy.cube.models.SkyDiffuseCube` for 3D cubes with
    an energy axis.

    Parameters
    ----------
    map : `~gammapy.maps.Map`
        Map template
    norm : float
        Norm parameter (multiplied with map values)
    meta : dict, optional
        Meta information, meta['filename'] will be used for serialization
    normalize : bool
        Normalize the input map so that it integrates to unity.
    interp_kwargs : dict
        Interpolation keyword arguments passed to `gammapy.maps.Map.interp_by_coord`.
        Default arguments are {'interp': 'linear', 'fill_value': 0}.
    """

    __slots__ = ["map", "norm", "meta", "_interp_kwargs", "filename"]

    def __init__(
        self, map, norm=1, meta=None, normalize=True, interp_kwargs=None, filename=None
    ):
        if (map.data < 0).any():
            log.warning("Diffuse map has negative values. Check and fix this!")

        self.map = map

        if normalize:
            self.normalize()

        self.norm = Parameter("norm", norm)
        self.meta = dict() if meta is None else meta

        interp_kwargs = {} if interp_kwargs is None else interp_kwargs
        interp_kwargs.setdefault("interp", "linear")
        interp_kwargs.setdefault("fill_value", 0)
        self._interp_kwargs = interp_kwargs
        self.filename = filename
        super().__init__([self.norm])

    @property
    def evaluation_radius(self):
        """Evaluation radius (`~astropy.coordinates.Angle`).

        Set to half of the maximal dimension of the map.
        """
        return np.max(self.map.geom.width) / 2.0

    def normalize(self):
        """Normalize the diffuse map model so that it integrates to unity."""
        data = self.map.data / self.map.data.sum()
        data /= self.map.geom.solid_angle().to_value("sr")
        self.map = self.map.copy(data=data, unit="sr-1")

    @classmethod
    def read(cls, filename, normalize=True, **kwargs):
        """Read spatial template model from FITS image.

        The default unit used if none is found in the file is ``sr-1``.

        Parameters
        ----------
        filename : str
            FITS image filename.
        normalize : bool
            Normalize the input map so that it integrates to unity.
        kwargs : dict
            Keyword arguments passed to `Map.read()`.
        """
        m = Map.read(filename, **kwargs)
        if m.unit == "":
            m.unit = "sr-1"
        return cls(m, normalize=normalize, filename=filename)

    def evaluate(self, lon, lat, norm):
        """Evaluate model."""
        coord = {"lon": lon.to_value("deg"), "lat": lat.to_value("deg")}
        val = self.map.interp_by_coord(coord, **self._interp_kwargs)
        return u.Quantity(norm.value * val, self.map.unit, copy=False)

    @property
    def position(self):
        """`~astropy.coordinates.SkyCoord`"""
        return self.map.geom.center_skydir

    @property
    def frame(self):
        return self.position.frame.name
