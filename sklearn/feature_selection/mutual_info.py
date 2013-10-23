# Author: Nikolay Mayorov <n59_ru@hotmail.com>
# License: 3-clause BSD
from __future__ import division

import numpy as np
from scipy.sparse import issparse
from scipy.special import digamma

from ..metrics.cluster.supervised import mutual_info_score
from ..neighbors import NearestNeighbors
from ..preprocessing import scale
from ..utils import check_random_state
from ..utils.validation import check_X_y


def _compute_mi_cc(x, y, n_neighbors):
    """Compute mutual information between two continuous variables.

    Parameters
    ----------
    x, y : ndarray
        Samples from random variables, 1-d arrays of identical shape.
    n_neighbors : int
        Number of nearest neighbors to search for each point, see [1]_.

    Returns
    -------
    mi : float
        Estimated mutual information. If it turned out to be negative it is
        replace by 0.

    Notes
    -----
    True mutual information can't be negative. If its estimate by a numerical
    method is negative, it means (providing the method is adequate) that the
    mutual information is close to 0 and replacing it by 0 is a reasonable
    strategy.

    References
    ----------
    .. [1] A. Kraskov, H. Stogbauer and P. Grassberger, "Estimating mutual
           information". Phys. Rev. E 69, 2004.
    """
    n_samples = x.size

    x = x.reshape((-1, 1))
    y = y.reshape((-1, 1))
    xy = np.hstack((x, y))

    nn = NearestNeighbors(metric='chebyshev', n_neighbors=n_neighbors)

    nn.fit(xy)
    radius = nn.kneighbors()[0]
    radius = np.nextafter(radius[:, -1], 0)

    nn.set_params(algorithm='kd_tree')

    nn.fit(x)
    ind = nn.radius_neighbors(radius=radius, return_distance=False)
    nx = np.array([i.size for i in ind])

    nn.fit(y)
    ind = nn.radius_neighbors(radius=radius, return_distance=False)
    ny = np.array([i.size for i in ind])

    mi = (digamma(n_samples) + digamma(n_neighbors) -
          np.mean(digamma(nx + 1)) - np.mean(digamma(ny + 1)))

    return max(0, mi)


def _compute_mi_cd(c, d, n_neighbors):
    """Compute mutual information between continuous and discrete variables.

    Parameters
    ----------
    c : ndarray
        Samples from a continuous random variable.
    d : ndarray
        Samples from a discrete random variable.
    n_neighbors : int
        Number of nearest neighbors to search for each point, see [1]_.

    Returns
    -------
    mi : float
        Estimated mutual information. If it turned out to be negative it is
        replace by 0.

    Notes
    -----
    True mutual information can't be negative. If its estimate by a numerical
    method is negative, it means (providing the method is adequate) that the
    mutual information is close to 0 and replacing it by 0 is a reasonable
    strategy.

    References
    ----------
    .. [1] B. C. Ross "Mutual Information between Discrete and Continuous
       Data Sets". PLoS ONE 9(2), 2014.
    """
    c = c.reshape((-1, 1))
    n_samples = c.size

    nn = NearestNeighbors(n_neighbors=n_neighbors)

    radius = np.empty(n_samples)
    label_counts = np.empty(n_samples)
    for label in np.unique(d):
        mask = d == label
        count = np.sum(mask)
        if count > 1:
            nn.set_params(n_neighbors=min(n_neighbors, count - 1))
            nn.fit(c[mask])
            r = nn.kneighbors()[0]
            radius[mask] = np.nextafter(r[:, -1], 0)
        else:
            radius[mask] = 0
        label_counts[mask] = count

    nn.set_params(algorithm='kd_tree')
    nn.fit(c)
    ind = nn.radius_neighbors(radius=radius, return_distance=False)
    neighbor_counts = np.array([i.size for i in ind])

    mi = (digamma(n_samples) + digamma(n_neighbors) -
          np.mean(digamma(label_counts)) -
          np.mean(digamma(neighbor_counts + 1)))

    return max(0, mi)


def _compute_mi(x, y, x_discrete, y_discrete, n_neighbors=3):
    """Compute mutual information between two variables.

    This is a simple wrapper which selects a proper function to call based on
    whether `x` and `y` are discrete or not.
    """
    if x_discrete and y_discrete:
        return mutual_info_score(x, y)
    elif x_discrete and not y_discrete:
        return _compute_mi_cd(y, x, n_neighbors)
    elif not x_discrete and y_discrete:
        return _compute_mi_cd(x, y, n_neighbors)
    else:
        return _compute_mi_cc(x, y, n_neighbors)


def _get_column(X, i):
    """Get column of a matrix.

    Parameters
    ----------
    X : ndarray or csc_matrix, shape (n_samples, n_features)
        Matrix from which to get a column.
    i : int
        Column index.

    Returns
    -------
    xi : ndarray, shape (n_samples,)
        i-th column of `X` in dense format.
    """
    if issparse(X):
        x = np.zeros(X.shape[0])
        start_ptr, end_ptr = X.indptr[i], X.indptr[i + 1]
        x[X.indices[start_ptr:end_ptr]] = X.data[start_ptr:end_ptr]
    else:
        x = X[:, i]

    return x


def _iterate_columns(X, columns=None):
    """Iterate over columns of a matrix.

    Parameters
    ----------
    X : ndarray or csc_matrix, shape (n_samples, n_features)
        Matrix over which to iterate.
    columns : iterable or None, default None
        Indices of columns to iterate over. If None, iterate over all columns.

    Yields
    ------
    x : ndarray, shape (n_samples,)
        Columns of `X` in dense format.
    """
    if columns is None:
        columns = range(X.shape[1])

    for i in columns:
        yield _get_column(X, i)


def mutual_info(X, y, discrete_features='auto', discrete_target=False,
                n_neighbors=3, copy=True, random_state=None):
    """Estimate mutual information (MI) between the features and the target.

    Read more in the :ref:`User Guide <univariate_feature_selection>`.

    Parameters
    ----------
    X : array_like or sparse matrix, shape (n_samples, n_features)
        Feature matrix.
    y : array_like, shape (n_samples,)
        Target vector.
    discrete_features : {'auto', bool, array_like}, default 'auto'
        If bool, then determines whether to consider all features discrete
        or continuous. If array, then it should be either a boolean mask
        with shape (n_features,) or array with indices of discrete features.
        If 'auto', assigned to False for dense `X` and to True for sparse `X`.
    discrete_target : bool, default False
        Whether to consider `y` as a discrete variable.
    n_neighbors : int, default 3
        Number of neighbors to use for MI estimation for continuous variables,
        see [2]_ and [3]_. Higher values reduce variance of the estimation, but
        could increase a bias.
    copy : bool, default True
        Whether to make a copy of the given data. If set to False, the initial
        data will be overwritten.
    random_state : int seed, RandomState instance, or None (default=None)
        The seed of the pseudo random number generator for adding small noise
        to continuous variables in order to remove repeated values.

    Returns
    -------
    mi : ndarray, shape (n_features,)
        Estimated mutual information between each feature and the target.

    Notes
    -----
    1. Terms "discrete feature" and "discrete target" are used instead of
       naming them as "categorical", because it describes the essence more
       accurately. For example, pixel intensities of an image are discrete
       features (but hardly categorical) and you will get better results if
       mark them as such. Also note, that treating a continuous variable as
       discrete and vice versa will usually give meaningless results, so be
       attentive about that.
    2. True mutual information can't be negative. If its estimate turned out
       to be negative, it will be replaced by zero.

    References
    ----------
    .. [1] H. Peng, F. Long, and C. Ding, "Feature selection based on mutual
           information: criteria of max-dependency, max-relevance, and
           min-redundancy", IEEE Transactions on Pattern Analysis and Machine
           Intelligence, Vol. 27, No. 8, pp. 1226-1238, 2005.
    .. [2] A. Kraskov, H. Stogbauer and P. Grassberger, "Estimating mutual
           information". Phys. Rev. E 69, 2004.
    .. [3] B. C. Ross "Mutual Information between Discrete and Continuous
           Data Sets". PLoS ONE 9(2), 2014.
    """
    X, y = check_X_y(X, y, accept_sparse='csc', y_numeric=not discrete_target)
    n_samples, n_features = X.shape

    if discrete_features == 'auto':
        discrete_features = issparse(X)

    if isinstance(discrete_features, bool):
        discrete_mask = np.empty(n_features, dtype=bool)
        discrete_mask.fill(discrete_features)
    else:
        discrete_features = np.asarray(discrete_features)
        if discrete_features.dtype != 'bool':
            discrete_mask = np.zeros(n_features, dtype=bool)
            discrete_mask[discrete_features] = True
        else:
            discrete_mask = discrete_features

    continuous_mask = ~discrete_mask
    if np.any(continuous_mask) and issparse(X):
        raise ValueError("Sparse matrix `X` can't have continuous features.")

    if copy:
        X = X.copy()

    if not discrete_target:
        X[:, continuous_mask] = scale(X[:, continuous_mask],
                                      with_mean=False, copy=False)

    # Add small noise to continuous features as advised in Kraskov et. al.
    rng = check_random_state(random_state)
    if np.any(continuous_mask):
        X = X.astype(float)
        means = np.maximum(1, np.mean(np.abs(X[:, continuous_mask]), axis=0))
        X[:, continuous_mask] += 1e-10 * means * rng.randn(
                n_samples, np.sum(continuous_mask))

    if not discrete_target:
        y = scale(y, with_mean=False)
        y += 1e-10 * np.maximum(1, np.mean(np.abs(y))) * rng.randn(n_samples)

    mi = [_compute_mi(x, y, discrete_feature, discrete_target) for
          x, discrete_feature in zip(_iterate_columns(X), discrete_mask)]

    return np.array(mi)