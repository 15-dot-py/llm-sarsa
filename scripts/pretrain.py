import argparse
import json
from pathlib import Path
from dataclasses import asdict
from sarsa import SARSAConfig
from sarsa.training import train
from evaluation.experiments import run_experiments,evaluate
from config.settings import ROOT
from data import process_csv

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--episodes',type=int,default=180)
    parser.add_argument('--warm-start-batches',type=int,default=1800)
    parser.add_argument('--include-llm',action='store_true'); args=parser.parse_args()
    cfg=SARSAConfig(episodes=args.episodes,architecture='dueling-v2',learning_rate=.0003)
    calibration=process_csv((ROOT/'data'/'sample_marketing.csv').read_bytes(),'demo')['current']
    def progress(c):
        if c['episode']%30==0: print(f"Episode {c['episode']}: reward={c['average_reward']:.4f}, loss={c['loss']:.4f}",flush=True)
    print('Training Deep SARSA (structured context)...',flush=True)
    deep,report=train(cfg,progress=progress,calibration=calibration,warm_start_batches=args.warm_start_batches)
    deep.save(ROOT/'data'/'pretrained.pt')
    print('Training observation-only Deep SARSA baseline...',flush=True)
    plain,plain_report=train(cfg,semantic=False,progress=progress,calibration=calibration,warm_start_batches=args.warm_start_batches)
    print('Training Tabular SARSA baseline...',flush=True)
    table,table_report=train(cfg,kind='tabular',semantic=False,progress=progress,calibration=calibration)
    print('Held-out common-seed evaluation...',flush=True)
    experiments=run_experiments(deep,table,plain,include_llm=args.include_llm)
    from sarsa import DeepSARSA
    from factor_engine import FactorEngine
    engine=FactorEngine(); untrained=DeepSARSA(engine.state_dim,cfg,engine.registry.signature)
    report['before_after']={'before':evaluate('结构化输入 Deep SARSA',untrained)['summary'],
                            'after':experiments['groups'][3]['summary'],
                            'source':'相同独立测试种子；随机初始化与预训练后，不保证提升'}
    report['baselines']={'plain_deep':plain_report,'tabular':table_report}
    (ROOT/'data'/'training_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'data'/'experiments.json').write_text(json.dumps(experiments,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved pretrained model and measured experiments.',flush=True)

if __name__=='__main__': main()
