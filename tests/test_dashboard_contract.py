import unittest
import pandas as pd
from src.dashboard_data import filter_period,metrics

class FilterContractTest(unittest.TestCase):
    def test_weighted_rate_and_report_overlap_follow_selected_dates(self):
        dates=pd.to_datetime(['2020-04-01','2020-04-02'])
        frames={
         'daily_metrics':pd.DataFrame({'reading_date':dates,'readings':[100,900],'loaded_readings':[100,900],'low_pressure_loaded_readings':[50,90]}),
         'hourly_investigation':pd.DataFrame({'hour_ts':dates,'candidate_status':['REVIEW_PRESSURE','NO_CANDIDATE']}),
         'incidents':pd.DataFrame({'starts_at':[dates[0]],'ends_at':[dates[0]+pd.Timedelta(hours=1)]}),
         'failure_reports':pd.DataFrame({'starts_at':[dates[0]],'ends_at':[dates[1]]})}
        both=metrics(filter_period(frames,'2020-04-01','2020-04-02'))
        self.assertAlmostEqual(both['low_pressure_share'],.14)
        last=metrics(filter_period(frames,'2020-04-02','2020-04-02'))
        self.assertEqual(last['reports'],0);self.assertEqual(last['incidents'],0)
        self.assertEqual(last['candidate_hours'],0);self.assertEqual(last['readings'],900)
        self.assertAlmostEqual(last['low_pressure_share'],.1)
        none=metrics(filter_period(frames,'2020-04-03','2020-04-03'))
        self.assertIsNone(none['low_pressure_share'])

if __name__=='__main__':unittest.main()
