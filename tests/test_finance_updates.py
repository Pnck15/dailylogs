"""Finance update must verify official GitHub release and SHA256."""
import unittest
from unittest.mock import Mock, patch
from car_finance_updates import fetch_finance_update, prepare_finance_update, REPO

TAG="v1.2.20"
PREFIX=f"https://github.com/{REPO}/releases/download/{TAG}/"
SHA="a"*64
HASH2="b"*64

def resp(payload):
    result=Mock()
    result.json.return_value=payload
    return result

def release():
    return [{
        "tag_name":TAG,"draft":False,"prerelease":False,
        "assets":[{"name":n,"browser_download_url":PREFIX+n}
                  for n in ("version.json","FinanceCalculator.exe","DailyLogUpdater.exe")],
    }]
def manifest():
    return {"version":"1.2.20","finance_version":"1.1.0",
      "finance_download_url":PREFIX+"FinanceCalculator.exe",
      "finance_sha256":SHA,
      "updater_download_url":PREFIX+"DailyLogUpdater.exe",
      "updater_sha256":HASH2}

class FinanceUpdateTests(unittest.TestCase):
    def test_update_detected_and_manifest_validated(self):
        with patch("car_finance_updates.requests.get",side_effect=[resp(release()),resp(manifest())]):
            self.assertTrue(fetch_finance_update("1.0.0")["available"])
        with patch("car_finance_updates.requests.get",side_effect=[resp(release()),resp(manifest())]):
            self.assertFalse(fetch_finance_update("1.1.0")["available"])

    def test_wrong_repo_asset_or_digest_rejected(self):
        for key,bad in (("finance_download_url","https://bad.example/app.exe"),
                        ("finance_sha256",""),("finance_version","invalid")):
            data=manifest()
            data[key]=bad
            with self.subTest(key=key),patch("car_finance_updates.requests.get",
                        side_effect=[resp(release()),resp(data)]):
                with self.assertRaises(ValueError):
                    fetch_finance_update("1.0.0")

    def test_staged_verified_files(self):
        result={"available":True,"updater_download_url":PREFIX+"DailyLogUpdater.exe",
                "updater_sha256":HASH2,"finance_download_url":PREFIX+"FinanceCalculator.exe",
                "finance_sha256":SHA}
        with patch("car_finance_updates.download_verified",side_effect=["helper","prepared"]) as fn:
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as folder:
                staged=prepare_finance_update(result,folder)
                self.assertEqual(staged["prepared_file"],"prepared")
                self.assertEqual(fn.call_count,2)

if __name__=="__main__":
    unittest.main()
