from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
STORAGE = Path(os.getenv('STORAGE_DIR', str(ROOT / 'storage'))).resolve()
STORAGE.mkdir(parents=True, exist_ok=True)
DATA_PATH = ROOT / 'data' / 'sample_marketing.csv'
PROFILE_LABELS = {
    'profit_maximization': '利润优先', 'growth_maximization': '销售增长',
    'inventory_clearance': '库存消化', 'customer_retention': '客户留存',
    'new_customer_acquisition': '新客拓展', 'acquisition_efficiency': '获客效率',
    'balanced_growth': '均衡经营',
}
