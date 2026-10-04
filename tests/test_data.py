import pytest
from data.generate import generate_sample
from data import process_csv
from factor_engine.selection import evaluate_factors

def test_demo_and_csv_metrics_and_no_fake_repeat(tmp_path):
    path=tmp_path/'demo.csv'; df=generate_sample(path)
    result=process_csv(path.read_bytes(),'demo')
    assert len(result['rows'])==300 and result['quality']['days']==60
    assert result['current']['roas']!=result['current']['roi']
    assert '代理' in result['quality']['warnings'][0]
    assert not result['quality']['estimates']
    assert result['daily'][0]['gmv_growth'] is None
    assert result['daily'][0]['inventory_level']==pytest.approx(sum(x['inventory'] for x in result['rows'][:5]))
    analysis=evaluate_factors(result['daily'])
    assert analysis['train_n']+analysis['test_n']==59
    assert len(analysis['importance'])==30

def test_gbk_missing_costs_validation(tmp_path):
    df=generate_sample(tmp_path/'x.csv',days=10).drop(columns=['cogs','unit_cost','return_loss'])
    data=process_csv(df.to_csv(index=False).encode('gb18030'))
    assert len(data['quality']['estimates'])==2
    df.loc[0,'clicks']=df.loc[0,'impressions']+1
    with pytest.raises(ValueError,match='clicks'): process_csv(df.to_csv(index=False).encode())
    with pytest.raises(ValueError,match='缺少'): process_csv(b'date,foo\n2026-01-01,1')
