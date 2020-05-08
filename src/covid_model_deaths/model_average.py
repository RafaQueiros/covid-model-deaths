import pandas as pd
import numpy as np

from covid_model_deaths.globals import COLUMNS

INDEX_COLUMNS = ['location_id', 'location', 'date', 'observed']
DRAW_COLUMNS = [f'draw_{i}' for i in range(1000)]


def load_data(data_path: str) -> pd.DataFrame:
    """Load data and convert time to pandas time stamp."""
    data = pd.read_csv(data_path)
    data['date'] = pd.to_datetime(data['date'])
    return data


def get_latest_data_date(today_data: pd.DataFrame) -> pd.Series:
    """Get the most recent date for which we have data by location.

    Parameters
    ----------
    today_data
        Today's model draws.

    Returns
    -------
        A series indexed by location id whose values are the last day for
        which we have data.

    """
    latest_date = today_data[today_data['observed']].groupby('location_id')['date'].max()
    return latest_date


def get_daily_predicted(data: pd.DataFrame, latest_data_date: pd.Series) -> pd.DataFrame:
    """Get the subset of predicted data corresponding to the latest data date."""
    # Subset the prediction to the locations shared by the current
    # dataset and the past datasets.
    data = data[data[COLUMNS.location_id].isin(latest_data_date.index)]
    data = data.set_index(COLUMNS.location_id)
    
    # Broadcast latest data date over the location index.
    min_date = latest_data_date.loc[data.index]
    # Get the current data data for the dataset so that we can compute the
    # predicted daily deaths on the first predicted date.
    to_average = data['date'] >= min_date
    data = (data
            .loc[to_average]
            .reset_index()
            .sort_values(['location_id', 'date'])
            .groupby(['location_id', 'location'])
            .apply(lambda x: (x.set_index('date') - x.set_index('date').shift(1)))
            .reset_index()
            .set_index('location_id'))
    # Now that we're in daily space, drop the last data date
    min_date = latest_data_date.loc[data.index]
    data = data.loc[data['date'] != min_date].reset_index()
    data['observed'] = False
    return data.loc[:, INDEX_COLUMNS + DRAW_COLUMNS]


def get_daily_observed(today_data: pd.DataFrame) -> pd.DataFrame:
    """Get the subset of observed daily deaths from today's draws."""
    today_data = (today_data
                  .loc[today_data['observed']]
                  .sort_values(INDEX_COLUMNS))
    today_daily_data = (today_data
                        .groupby(['location_id', 'location', 'observed'])
                        .apply(lambda x: x.set_index('date') - x.set_index('date').shift(1))
                        .reset_index()
                        .set_index(INDEX_COLUMNS))
    # Assume the first observed deaths occurred the first day of observation.
    today_data = today_data.set_index(INDEX_COLUMNS)
    to_replace = today_daily_data.isnull().sum(axis=1) > 0
    today_daily_data.loc[to_replace] = today_data.loc[to_replace]
    return today_daily_data.reset_index()


def get_daily_predictions(today_data: pd.DataFrame, yesterday_data: pd.DataFrame,
                          day_before_yesterday_data: pd.DataFrame) -> pd.DataFrame:
    """Gather all predicted data across datasets."""
    latest_date = get_latest_data_date(today_data)
    today_predicted = get_daily_predicted(today_data, latest_date)
    yesterday_predicted = get_daily_predicted(yesterday_data, latest_date)
    day_before_yesterday_predicted = get_daily_predicted(day_before_yesterday_data, latest_date)
    all_predicted = pd.concat([today_predicted, yesterday_predicted, day_before_yesterday_predicted],
                              ignore_index=True)
    return all_predicted


def avg_within_window(data: pd.DataFrame, start_day: pd.DataFrame, end_day: pd.DataFrame) -> pd.DataFrame:
    data = data.merge(start_day)
    data = data.merge(end_day)
    
    window_start = data['date'] >= data['start_day']
    window_end = data['date'] < data['end_day']
    del data['start_day']
    del data['end_day']
    
    data.loc[window_start & window_end, 'observed'] = False
    
    data = data.sort_values(['location_id', 'date']).reset_index(drop=True)
    first_day = data['date'] == data.groupby('location_id').date.transform(min)
    delta_draws = data[DRAW_COLUMNS].values[1:] - data[DRAW_COLUMNS].values[:-1]
    delta_draws = delta_draws[~first_day.values[1:]]
    data.loc[~first_day, DRAW_COLUMNS] = delta_draws
    
    means = data.loc[window_start & window_end, DRAW_COLUMNS].mean(axis=1).values
    data.loc[window_start & window_end, DRAW_COLUMNS] = np.array([means]).T.repeat(len(DRAW_COLUMNS), axis=1)
    
    data = data.sort_values(['location_id', 'date']).reset_index(drop=True)
    data[DRAW_COLUMNS] = data.groupby('location_id', as_index=False)[DRAW_COLUMNS].cumsum()
    
    return data
    

def set_past_avg_window(today_data: pd.DataFrame, yesterday_data: pd.DataFrame, 
                        day_before_yesterday_data: pd.DataFrame, past_avg_window: int) -> pd.DataFrame:
    """Days in past over which we will average, using mean for previous days"""
    start_day = today_data[today_data['observed']].groupby('location_id').date.max() - pd.Timedelta(days=past_avg_window)
    start_day = start_day.reset_index()
    start_day = start_day.rename(index=str, columns={'date':'start_day'})

    end_day = today_data[~today_data['observed']].groupby('location_id').date.min()
    end_day = end_day.reset_index()
    end_day = end_day.rename(index=str, columns={'date':'end_day'})
    
    today_data = avg_within_window(today_data, start_day, end_day)
    yesterday_data = avg_within_window(yesterday_data, start_day, end_day)
    day_before_yesterday_data = avg_within_window(day_before_yesterday_data, start_day, end_day)
    
    return today_data, yesterday_data, day_before_yesterday_data, end_day


def reset_observed(data: pd.DataFrame, end_day: pd.DataFrame):
    data = data.merge(end_day)
    
    window_end = data['date'] < data['end_day']
    del data['end_day']
    data.loc[window_end, 'observed'] = True
    return data


def moving_average_predictions(today_data_path: str, yesterday_data_path: str,
                               day_before_yesterday_path: str,
                               past_avg_window: int) -> pd.DataFrame:
    """Average the predictions for recent 3 runs."""
    print("Averaging over the following files: ", [today_data_path, yesterday_data_path, day_before_yesterday_path])
    today_data = load_data(today_data_path)
    yesterday_data = load_data(yesterday_data_path)
    day_before_yesterday_data = load_data(day_before_yesterday_path)
    
    today_data, yesterday_data, day_before_yesterday_data, end_day = set_past_avg_window(
        today_data, yesterday_data, day_before_yesterday_data, past_avg_window
    )

    observed_data = get_daily_observed(today_data)
    all_predicted = get_daily_predictions(today_data, yesterday_data, day_before_yesterday_data)
    prediction_average = all_predicted.groupby(INDEX_COLUMNS).mean().reset_index()
    combined = pd.concat([observed_data, prediction_average], ignore_index=True)
    cumulative = (combined.groupby(['location_id', 'location'], as_index=False)
                  .apply(lambda x: x.set_index(['location_id', 'location', 'date', 'observed']).cumsum())
                  .reset_index()
                  .drop(columns='level_0'))
    
    cumulative = reset_observed(cumulative, end_day)
    
    return cumulative
