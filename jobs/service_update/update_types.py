from enum import Enum


class UpdateType(Enum):
    KustomizeChart = 0
    Image = 1
    HelmChart = 2
