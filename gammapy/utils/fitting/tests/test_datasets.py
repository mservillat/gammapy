# Licensed under a 3-clause BSD style license - see LICENSE.rst
import pytest
from numpy.testing import assert_allclose
from gammapy.utils.fitting import Datasets
from .test_fit import MyDataset


@pytest.fixture(scope="session")
def datasets():
    return Datasets([MyDataset(), MyDataset()])


class TestDatasets:
    @staticmethod
    def test_types(datasets):
        assert datasets.is_all_same_type

    @staticmethod
    def test_likelihood(datasets):
        likelihood = datasets.likelihood()
        assert_allclose(likelihood, 0)

    @staticmethod
    def test_str(datasets):
        assert "MyDataset: 2" in str(datasets)
