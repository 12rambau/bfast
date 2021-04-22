'''
Created on Nov 17, 2020


@author: mortvest
'''

import numpy as np
import statsmodels.api as sm

from bfast.base import BFASTBase
from .utils import different, omit_nans, partition_matrix, create_nan_map
from .stl import STL
from .efp import EFP
from .breakpoints import Breakpoints


class BFASTPython(BFASTBase):
    """
    Python implementation of the BFAST algorithm:
    https://www.rdocumentation.org/packages/bfast/versions/1.5.7/topics/bfast

    Iterative break detection in seasonal and trend component of a time
    series. Seasonal breaks is a function that combines the iterative
    decomposition of time series into trend, seasonal and remainder
    components with significant break detection in the decomposed
    components of the time series.

    Parameters
    ----------
    frequency : int

    h : float, default=0.15

    season : string, default="dummy"

    max_iter : int, default=10

    max_breaks : int, optional

    level : float, default=0.05

    verbose : int, optional (default=0)
        The verbosity level (0=no output, 1=info, 2=debug).

    Attributes
    ----------
    trend : ndarray

    season : ndarray

    remainder : ndarray

    trend_breakpoints : ndarray

    season_breakpoints : ndarray

    n_trend_breakpoints : ndarray

    n_season_breakpoints : ndarray

    """

    def __init__(self,
                 frequency,
                 h=0.15,
                 season_type="dummy",
                 max_iter=10,
                 max_breaks=None,
                 level=0.05,
                 verbose=0,
                ):
        super(BFASTPython, self).__init__(frequency=frequency,
                                          h=h,
                                          season_type=season_type,
                                          max_iter=max_iter,
                                          max_breaks=max_breaks,
                                          level=level,
                                          verbose=verbose)


    def fit(self, Yt, ti):
        """ Fits the models for the ndarray 'data'

        Parameters
        ----------
        Yt: ndarray of shape (N, W, H),
            where N is the number of time
            series points per pixel and W
            and H the width and the height
            of the image, respectively.
        ti : array

        Returns
        -------
        self : The BFAST object.
        """
        smod = self.build_seasonal_model(ti)

        trend_global = np.zeros(Yt.shape, dtype=np.float32)
        season_global = np.zeros(Yt.shape, dtype=np.float32)
        remainder_global = np.zeros(Yt.shape, dtype=np.float32)
        trend_breakpoints_global = np.zeros(Yt.shape, dtype=np.int32)
        season_breakpoints_global = np.zeros(Yt.shape, dtype=np.int32)
        n_trend_breakpoints_global = np.zeros((Yt.shape[1], Yt.shape[2]), dtype=np.int32)
        n_season_breakpoints_global = np.zeros((Yt.shape[1], Yt.shape[2]), dtype=np.int32)

        for i in range(Yt.shape[1]):
            if self.verbose > 0:
                print("Processing row {}".format(i))
            for j in range(Yt.shape[2]):
                y = Yt[:,i,j]
                pix_trend, \
                    pix_season, \
                    pix_remainder, \
                    pix_trend_br, \
                    pix_season_br, \
                    pix_n_trend_br, \
                    pix_n_season_br = self.fit_single(y, ti, smod)

                trend_global[:, i, j] = pix_trend
                season_global[:, i, j] = pix_season
                remainder_global[:, i, j] = pix_remainder
                trend_breakpoints_global[:, i, j] = pix_trend_br
                season_breakpoints_global[:, i, j] = pix_season_br
                n_trend_breakpoints_global[i, j] = pix_n_trend_br
                n_season_breakpoints_global[i, j] = pix_n_season_br

        self.trend = trend_global
        self.season = season_global
        self.remainder = remainder_global
        self.trend_breakpoints = trend_breakpoints_global
        self.season_breakpoints = season_breakpoints_global
        self.n_trend_breakpoints = n_trend_breakpoints_global
        self.n_season_breakpoints = n_season_breakpoints_global

        return self

    def fit_single(self, Yt_n, ti_n, smod_n):
        """ Fits the BFAST model for the 1D array y.

        Parameters
        ----------
        Yt_n   : array
            observations (with NaNs)
        ti_n   : array
            times
        smod_n : ndarray
            seasonal model matrix

        Returns
        -------
        Tt_n : array
            Trend component for one pixel
        St_n : array
            Seasonal component for one pixel
        Nt_n : array
            Remainder component for one pixel
        Vt_bp_arr : array
            Array of breakpoint indexes in the trend component, padded with 0s to have
            the same length as time series
        Wt_bp_arr : array
            Same, but for the seasonal component
        n_Vt_bp : int
            Number of breakpoints in the trend component
        n_Wt_bp : int
            Number of breakpoints in the seasonal component
        """
        nrow_n = Yt_n.shape[0]

        # Decompose time series to find the initial seasonal component, if required
        if self.season_type in ["dummy", "harmonic"]:
            if self.verbose > 0:
                print("Applying STL")
            St_n = STL(Yt_n, self.frequency).seasonal
            if self.verbose > 1:
                print("St set to\n{}".format(St_n))
        else:
            # no seasonal model
            St_n = np.zeros(nrow_n)

        # filter out nans
        nan_map = create_nan_map(Yt_n)
        ti = ti_n[nan_map]
        St = St_n[nan_map]
        Yt = Yt_n[nan_map]
        if smod_n is not None:
            smod = smod_n[nan_map]
        nrow = Yt.shape[0]

        Vt_bp = np.array([], dtype=np.int32)
        Wt_bp = np.array([], dtype=np.int32)
        CheckTimeTt = np.array([0], dtype=np.int32)
        CheckTimeSt = np.array([0], dtype=np.int32)
        i_iter = 1

        while (different(Vt_bp, CheckTimeTt) or different(Vt_bp, CheckTimeTt)) and i_iter < self.max_iter:
            if self.verbose > 0:
                print("BFAST iteration #{}".format(i_iter))
            CheckTimeTt = Vt_bp
            CheckTimeSt = Wt_bp

            ### Change in trend component
            Vt = Yt - St  # Deseasonalized Time series
            if self.verbose > 1:
                print("Vt:\n{}".format(Vt))
            p_Vt = EFP(sm.add_constant(ti), Vt, self.h, verbose=self.verbose).sctest()
            if p_Vt <= self.level:
                if self.verbose > 0:
                    print("Breakpoints in trend detected")
                ti1, Vt1 = omit_nans(ti, Vt)
                if self.verbose > 0:
                    print("Finding breakpoints in trend")
                bp_Vt = Breakpoints(sm.add_constant(ti1),
                                    Vt1,
                                    h=self.h,
                                    max_breaks=self.max_breaks,
                                    verbose=self.verbose)
                nobp_Vt = len(bp_Vt.breakpoints) == 0
            else:
                if self.verbose > 0:
                    print("No breakpoints in trend detected")
                nobp_Vt = True

            if self.verbose > 0:
                print("Fitting linear model for trend")
            if nobp_Vt:
                ## No Change detected
                fm0 = sm.OLS(Vt, ti, missing='drop').fit()
                Vt_bp = np.array([], dtype=np.int32)  # no breaks times

                Tt = fm0.predict(exog=ti)
            else:
                part = bp_Vt.breakfactor()
                X1 = partition_matrix(part, sm.add_constant(ti[~np.isnan(Yt)]))

                fm1 = sm.OLS(Yt, X1, missing='drop').fit()
                Vt_bp = bp_Vt.breakpoints

                Tt = fm1.predict()

            ### Change in seasonal component
            if self.season_type == "none":
                # there is no season
                St = np.zeros(nrow).astype(float)
            else:
                Wt = Yt - Tt
                p_Wt = EFP(smod, Wt, self.h, verbose=self.verbose).sctest()  # preliminary test
                if p_Wt <= self.level:
                    if self.verbose > 0:
                        print("Breakpoints in season detected")
                    if self.verbose > 0:
                        print("Finding breakpoints in season")
                    bp_Wt = Breakpoints(smod,
                                        Wt,
                                        h=self.h,
                                        max_breaks=self.max_breaks,
                                        verbose=self.verbose)
                    nobp_Wt = len(bp_Wt.breakpoints) == 0
                else:
                    if self.verbose > 0:
                        print("No breakpoints in season detected")
                    nobp_Wt = True

                if self.verbose > 0:
                    print("Fitting linear model for season")
                if nobp_Wt:
                    ## No seasonal change detected
                    sm0 = sm.OLS(Wt, smod, missing='drop').fit()
                    St = sm0.predict()
                    Wt_bp = np.array([], dtype=np.int32)
                else:
                    part = bp_Wt.breakfactor()
                    if self.season_type in ["dummy", "harmonic"]:
                        X_sm1 = partition_matrix(part, smod)

                    sm1 = sm.OLS(Wt, X_sm1, missing='drop').fit()
                    Wt_bp = nan_map[bp_Wt.breakpoints]
                    St = sm1.predict()

            # remainder
            Nt = Yt - Tt - St
            i_iter += 1

        # Overwrite non-missing with fitted values
        nans = np.repeat(np.nan, nrow_n)
        Tt_n = np.copy(nans)
        Tt_n[nan_map] = Tt
        St_n = np.copy(nans)
        St_n[nan_map] = St
        Nt_n = np.copy(nans)
        Nt_n[nan_map] = Nt

        # modify breakpoint indexes to work with nan values
        Vt_bp_n = nan_map[Vt_bp]
        Wt_bp_n = nan_map[Wt_bp]

        # Pad breakpoint arrays with 0s
        Vt_bp_arr = np.zeros(nrow_n, dtype=np.int32)
        Vt_bp_arr[:len(Vt_bp_n)] = np.array(Vt_bp_n)
        Wt_bp_arr = np.zeros(nrow_n, dtype=np.int32)
        Wt_bp_arr[:len(Wt_bp_n)] = np.array(Wt_bp_n)

        return Tt_n, St_n, Nt_n, Vt_bp_arr, Wt_bp_arr, len(Vt_bp), len(Wt_bp)

    def build_seasonal_model(self, ti):
        f = self.frequency
        nrow = ti.shape[0]
        smod = None
        if self.season_type == "harmonic":
            if self.verbose > 0:
                print("'harmonic' season is chosen")
            w = 1/f
            tl = np.arange(1, nrow + 1)
            co = np.cos(2 * np.pi * tl * w)
            si = np.sin(2 * np.pi * tl * w)
            co2 = np.cos(2 * np.pi * tl * w * 2)
            si2 = np.sin(2 * np.pi * tl * w * 2)
            co3 = np.cos(2 * np.pi * tl * w * 3)
            si3 = np.sin(2 * np.pi * tl * w * 3)
            smod = np.column_stack((co, si, co2, si2, co3, si3))
        elif self.season_type == "dummy":
            if self.verbose > 0:
                print("'dummy' season is chosen")

            eye_box = np.row_stack((np.eye(f - 1), np.repeat(-1, f - 1)))
            n_boxes = int(np.ceil(nrow / f))

            smod = np.tile(eye_box, (n_boxes, 1))
            smod = smod[:nrow]
            smod = sm.add_constant(smod)
        elif self.season_type == "none":
            if self.verbose > 0:
                print("'none' season is chosen")
                print("No sesonal model will be fitted!")
        else:
            raise ValueError("Seasonal model is unknown, use 'harmonic', 'dummy' or 'none'")

        return smod