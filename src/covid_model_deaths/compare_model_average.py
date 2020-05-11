from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd


def fill_draw(df: pd.DataFrame) -> pd.DataFrame:
    """Replace last missing draw with second to last draw."""
    # FIXME: Yikes, what's this about?
    if 'draw_999' not in df.columns:
        df['draw_999'] = df['draw_998']
    return df


class CompareAveragingModelDeaths:
    """Compare current model results to previous results."""

    def __init__(self, raw_draw_path: str, average_draw_path: str,
                 yesterday_draw_path: str, before_yesterday_draw_path: str,
                 raw_data: pd.DataFrame,
                 draws: List[str] = [f'draw_{i}' for i in range(1000)]):
        self.old_name = Path(raw_draw_path).parent.name
        self.old_df = pd.read_csv(raw_draw_path)
        self.old_df = fill_draw(self.old_df)
        self.new_df = pd.read_csv(average_draw_path)
        self.new_df = fill_draw(self.new_df)
        self.yesterday_name = Path(yesterday_draw_path).parent.name
        self.yesterday_df = pd.read_csv(yesterday_draw_path)
        self.yesterday_df = fill_draw(self.yesterday_df)
        self.before_yesterday_name = Path(before_yesterday_draw_path).parent.name
        self.before_yesterday_df = pd.read_csv(before_yesterday_draw_path)
        self.before_yesterday_df = fill_draw(self.before_yesterday_df)
        self.raw_data = raw_data.copy()
        self.draws = draws

    @staticmethod
    def _get_deaths_per_day(draw_df: pd.DataFrame, draws: List[str]) -> pd.DataFrame:
        draw_df = draw_df.sort_values(['location', 'date']).reset_index(drop=True).copy()
        if 'peak_date' not in draw_df.columns:
            draw_df['peak_date'] = False
        delta = draw_df[draws].values[1:,:] - draw_df[draws].values[:-1,:]
        draw_df.iloc[1:][draws] = delta
        draw_df['day0'] = draw_df.groupby('location', as_index=False)['date'].transform('min')
        draw_df = draw_df.loc[draw_df['date'] != draw_df['day0']]
        draw_df['val_mean'] = draw_df[draws].mean(axis=1)
        draw_df['val_lower'] = np.percentile(draw_df[draws], 2.5, axis=1)
        draw_df['val_upper'] = np.percentile(draw_df[draws], 97.5, axis=1)

        return draw_df[['location_id', 'location', 'date', 'peak_date', 'observed', 'val_mean', 'val_lower', 'val_upper']]

    def _summarize(self, agg_location: Optional[str], df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        df['date'] = pd.to_datetime(df['date'])
        if 'peak_date' not in df.columns:
            df['peak_date'] = False
        if agg_location is not None:
            agg_old_df = df.groupby('date', as_index=False)[self.draws].sum()
            agg_old_df['location'] = agg_location
            agg_old_df['location_id'] = -1
            agg_old_df['peak_date'] = False
            agg_old_df['observed'] = False
            df = agg_old_df[df.columns].append(df).reset_index(drop=True)
        df['val_mean'] = df[self.draws].mean(axis=1)
        df['val_lower'] = np.percentile(df[self.draws], 2.5, axis=1)
        df['val_upper'] = np.percentile(df[self.draws], 97.5, axis=1)
        daily_df = self._get_deaths_per_day(df, self.draws)
        df = df[['location_id', 'location', 'date', 'peak_date', 'observed', 'val_mean', 'val_lower', 'val_upper']]
        return df, daily_df

    def _summarize_draws(self, agg_location: Optional[str]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame,
                                                                     pd.DataFrame, pd.DataFrame, pd.DataFrame,
                                                                     pd.DataFrame, pd.DataFrame]:
        old_df = self.old_df.copy()
        old_df, old_daily_df = self._summarize(agg_location, old_df)

        new_df = self.new_df.copy()
        new_df, new_daily_df = self._summarize(agg_location, new_df)

        yesterday_df = self.yesterday_df.copy()
        yesterday_df, yesterday_daily_df = self._summarize(agg_location, yesterday_df)

        before_yesterday_df = self.before_yesterday_df.copy()
        before_yesterday_df, before_yesterday_daily_df = self._summarize(agg_location, before_yesterday_df)

        return (old_df, old_daily_df, new_df, new_daily_df,
                yesterday_df, yesterday_daily_df, before_yesterday_df, before_yesterday_daily_df)

    def make_some_pictures(self, pdf_out_path: str, agg_location: str = None) -> None:
        """Plot old averages and deaths versus new averages and deaths."""
        old_df, old_daily_df, new_df, new_daily_df, \
            yesterday_df, yesterday_daily_df, before_yesterday_df, before_yesterday_daily_df \
            = self._summarize_draws(agg_location)
        with PdfPages(pdf_out_path) as pdf:
            for location in new_df['location'].unique():
                fig, ax = plt.subplots(1, 2, figsize=(16.5, 8.5))
                # get peak date
                if any(new_df.loc[new_df['location'] == location, 'peak_date']):
                    peak_date = new_df.loc[(new_df['location'] == location) & (new_df['peak_date']), 'date'].item()
                else:
                    peak_date = None

                # cumulative
                location_id = new_df.loc[new_df['location'] == location, 'location_id'].reset_index(drop=True)[0]
                loc_raw_data = self.raw_data.loc[self.raw_data['location_id'] == location_id].reset_index(drop=True)
                ax[0].plot(
                    loc_raw_data['Date'],
                    loc_raw_data['Deaths'],
                    alpha=0.5, color='black'
                )
                ax[0].scatter(
                    loc_raw_data['Date'],
                    loc_raw_data['Deaths'],
                    alpha=0.5, c='darkgrey', edgecolors='black', label='observed'
                )
                ax[0].fill_between(
                    old_df.loc[old_df['location'] == location, 'date'],
                    old_df.loc[old_df['location'] == location, 'val_lower'],
                    old_df.loc[old_df['location'] == location, 'val_upper'],
                    alpha=0.25, color='dodgerblue'
                )
                ax[0].plot(
                    old_df.loc[old_df['location'] == location, 'date'],
                    old_df.loc[old_df['location'] == location, 'val_mean'],
                    color='dodgerblue', label=self.old_name
                )
                ax[0].fill_between(
                    new_df.loc[new_df['location'] == location, 'date'],
                    new_df.loc[new_df['location'] == location, 'val_lower'],
                    new_df.loc[new_df['location'] == location, 'val_upper'],
                    alpha=0.25, color='firebrick'
                )
                ax[0].plot(
                    new_df.loc[new_df['location'] == location, 'date'],
                    new_df.loc[new_df['location'] == location, 'val_mean'],
                    color='firebrick', label='3-day Predictions Average'
                )

                ax[0].fill_between(
                    yesterday_df.loc[yesterday_df['location'] == location, 'date'],
                    yesterday_df.loc[yesterday_df['location'] == location, 'val_lower'],
                    yesterday_df.loc[yesterday_df['location'] == location, 'val_upper'],
                    alpha=0.15, color='limegreen'
                )
                ax[0].plot(
                    yesterday_df.loc[yesterday_df['location'] == location, 'date'],
                    yesterday_df.loc[yesterday_df['location'] == location, 'val_mean'],
                    color='limegreen', label=self.yesterday_name
                )

                ax[0].fill_between(
                    before_yesterday_df.loc[before_yesterday_df['location'] == location, 'date'],
                    before_yesterday_df.loc[before_yesterday_df['location'] == location, 'val_lower'],
                    before_yesterday_df.loc[before_yesterday_df['location'] == location, 'val_upper'],
                    alpha=0.15, color='khaki'
                )
                ax[0].plot(
                    before_yesterday_df.loc[before_yesterday_df['location'] == location, 'date'],
                    before_yesterday_df.loc[before_yesterday_df['location'] == location, 'val_mean'],
                    color='khaki', label=self.before_yesterday_name
                )

                ax[0].set_xlabel('Date')
                ax[0].set_ylabel('Cumulative deaths')

                # daily
                ax[1].plot(
                    loc_raw_data['Date'][1:],
                    loc_raw_data['Deaths'].values[1:] - loc_raw_data['Deaths'].values[:-1],
                    alpha=0.5, color='black'
                )
                ax[1].scatter(
                    loc_raw_data['Date'][1:],
                    loc_raw_data['Deaths'].values[1:] - loc_raw_data['Deaths'].values[:-1],
                    alpha=0.5, c='darkgrey', edgecolors='black', label='observed'
                )
                ax[1].fill_between(
                    old_daily_df.loc[old_daily_df['location'] == location, 'date'],
                    old_daily_df.loc[old_daily_df['location'] == location, 'val_lower'],
                    old_daily_df.loc[old_daily_df['location'] == location, 'val_upper'],
                    alpha=0.25, color='dodgerblue'
                )
                ax[1].plot(
                    old_daily_df.loc[old_daily_df['location'] == location, 'date'],
                    old_daily_df.loc[old_daily_df['location'] == location, 'val_mean'],
                    color='dodgerblue', label=self.old_name
                )

                ax[1].fill_between(
                    new_daily_df.loc[new_daily_df['location'] == location, 'date'],
                    new_daily_df.loc[new_daily_df['location'] == location, 'val_lower'],
                    new_daily_df.loc[new_daily_df['location'] == location, 'val_upper'],
                    alpha=0.25, color='firebrick'
                )
                ax[1].plot(
                    new_daily_df.loc[new_daily_df['location'] == location, 'date'],
                    new_daily_df.loc[new_daily_df['location'] == location, 'val_mean'],
                    color='firebrick', label='3-day Predictions Average'
                )

                ax[1].fill_between(
                    yesterday_daily_df.loc[yesterday_daily_df['location'] == location, 'date'],
                    yesterday_daily_df.loc[yesterday_daily_df['location'] == location, 'val_lower'],
                    yesterday_daily_df.loc[yesterday_daily_df['location'] == location, 'val_upper'],
                    alpha=0.15, color='limegreen'
                )
                ax[1].plot(
                    yesterday_daily_df.loc[yesterday_daily_df['location'] == location, 'date'],
                    yesterday_daily_df.loc[yesterday_daily_df['location'] == location, 'val_mean'],
                    color='limegreen', label=self.yesterday_name
                )

                ax[1].fill_between(
                    before_yesterday_daily_df.loc[before_yesterday_daily_df['location'] == location, 'date'],
                    before_yesterday_daily_df.loc[before_yesterday_daily_df['location'] == location, 'val_lower'],
                    before_yesterday_daily_df.loc[before_yesterday_daily_df['location'] == location, 'val_upper'],
                    alpha=0.15, color='khaki'
                )
                ax[1].plot(
                    before_yesterday_daily_df.loc[before_yesterday_daily_df['location'] == location, 'date'],
                    before_yesterday_daily_df.loc[before_yesterday_daily_df['location'] == location, 'val_mean'],
                    color='khaki', label=self.before_yesterday_name
                )

                if peak_date is not None:
                    ax[0].axvline(peak_date, color='black', linestyle='--', alpha=0.75)
                    ax[1].axvline(peak_date, color='black', linestyle='--', alpha=0.75)

                ax[1].set_xlabel('Date')
                ax[1].set_ylabel('Daily deaths')

                plt.xticks(rotation=60)
                plt.suptitle(location)
                plt.legend()
                plt.tight_layout()
                pdf.savefig()
