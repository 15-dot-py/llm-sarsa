export type Num = number | null;
export type PageId = 'dashboard' | 'decision' | 'lab' | 'data' | 'library' | 'history' | 'experiments';
export interface Channel { channel: string; revenue: number; advertising_cost: number; profit: number; roi: Num; cac: Num; inventory: number; conversion_rate: number; }
export interface Metrics {
  date: string; revenue: number; sales: Num; profit: number; roi: Num; roas?: Num; cac: Num;
  conversion_rate: Num; repeat_purchase_rate: Num; inventory_pressure: Num; inventory_level: number;
  profit_margin: Num; advertising_budget: Num; inventory_turnover: Num; gmv_growth: Num;
  channels: Channel[]; cost_method: string; promotion_cost?: Num; price_level?: Num;
}
export interface Factor {
  name: string; description: string; category: string; raw: Num; normalized: number;
  min_value: number; max_value: number; enabled: boolean; available: boolean;
  provenance: string; source: string; clipped: boolean; controllable: boolean; lag: number;
}
export interface State { vector: number[]; factors: Factor[]; signature: string; state_dim: number; coverage: number; layout: string; }
export interface Quality { rows: number; days: number; start: string; end: string; label: string; source: string; warnings: string[]; estimates: string[]; cost_method: string; encoding: string; latest_result_source?: string; }
export interface Bias { name: string; label: string; score: Num; status: string; evidence: unknown[]; interpretation: string; }
export interface Profile { name: string; label: string; weights: Record<string, number>; version: string; }
export interface RewardCatalog {
  version: string; normalization: string; formula: string; weight_rule: string; boundary: string;
  factors: {name:string;label:string;formula:string;note:string;sign:number;lower:number;upper:number}[];
  profiles: (Profile & {raw_weights:Record<string,number>})[];
}
export interface LLMStatus { available: boolean; configured?: boolean; last_error?: string | null; last_success_at?: string | null; last_used_model?: string | null; free_only?: boolean; mode: string; model: string; calls_today: number; daily_limit: number; }
export interface Dashboard { metrics: Metrics; series: Metrics[]; quality: Quality; state: State; bias: Bias[]; llm: LLMStatus; training_status: string; model_version: string; active_decision: Decision | null; profiles: Profile[]; }
export interface Importance { name: string; label: string; permutation_mean: number; permutation_std: number; spearman: Num; q_sensitivity: Num; present: boolean; }
export interface FactorAnalysis { importance: Importance[]; method: string; target: string; warning: string; status: string; train_n?: number; test_n?: number; test_mse?: number; }
export interface QValue { index: number; name: string; label: string; q: number; legal: boolean; reasons: string[]; }
export interface RewardTerm { name: string; raw: Num; normalized: number; weight: number; sign: number; contribution: number; available: boolean; }
export interface Reward { total: number; contributions: RewardTerm[]; missing: string[]; coverage: number; profile: string; }
export interface Update { loss: number; q_before: number; target: number; bootstrap_q: number; next_action: number | null; reward: number; terminal: boolean; gradient_norm: number; updates: number; algorithm: string; }
export interface Transition { state: number[]; action: number; reward: number; next_state: number[]; next_action: number | null; next_action_name?: string; next_action_confirmed: boolean; source: string; terminal: boolean; update?: Update; model_version_after?: string; }
export interface Explanation { selected_action: string; source: string; model?: string | null; provider?: string; summary: string; reasons: string[]; watch_metrics: string[]; limitations: string[]; fallback_reason: string | null; }
export interface Decision {
  input_audit?: {used_signals:{name:string;description:string;value:Num}[];business_claims:Record<string,string>;data_source:string;note:string;goal_source?:string;explicit_constraints?:string[]};
  company_evidence?: CompanyEvidence[];
  id: string; timestamp: string; status: string; question: string; model_version: string;
  state_vector: number[]; factor_values: Factor[]; factor_importance: FactorAnalysis; factor_signature: string;
  action: number; action_name: string; action_label: string; q_values: QValue[]; q_selected: number;
  expected_reward: { mean: Num; low: Num; high: Num; source: string; n: number; };
  actual_reward: Reward | null; reward_profile: string; reward_weights: number[];
  decision_source: string; explanation_source: string; explanation: Explanation;
  semantic: { source: string; model?: string | null; provider?: string; fallback_reason: string | null; signals: { summary: string; inventory_pressure: string; douyin_cac: string; repeat_purchase: string; evidence: string[]; unknowns: string[]; holiday_index: Num; competitor_intensity: Num; platform_traffic_change: Num; market_demand_index: Num; } };
  bias: Bias[]; mask_reasons: Record<string, string[]>; metrics: Metrics; parent_decision: string | null;
  execution: { action: number; action_name: string; timestamp: string; override: boolean; execution_source: string; } | null;
  user_feedback: { rating: string; mode: string; provenance: { label: string; source: string; }; } | null;
  transition: Transition | null; previous_update?: Update; next_decision?: string;
}
export interface Curve { episode: number; average_reward: number; loss: number; epsilon: number; average_q: number; last_action: number; reward_profile: string; rewards: number[]; actions: number[]; }
export interface Summary { average_reward: number; roi: number; profit: number; conversion_rate: number; cac: number; inventory_turnover: number; reward_std: number; decision_stability: number; reward_standard_error: number; }
export interface ExperimentGroup { name: string; status: string; reason?: string; summary: Summary | null; n_episodes?: number; horizon?: number; }
export interface Experiments { groups: ExperimentGroup[]; ablations: { group: string; masked_factors: string[]; reward: number; difference_from_full: number; method: string; }[]; source: string; test_seeds: number[]; horizon: number; semantic_boundary: string; }
export interface TrainingReport { curves: Curve[]; algorithm: string; source: string; config: Record<string, number | string>; before_after?: { before: Summary; after: Summary; source: string; }; }
export interface Lab { training: TrainingReport | null; experiments: Experiments | null; importance: FactorAnalysis; updates: number; model_version: string; network: string; epsilon: number; config: Record<string, number | string>; current_state: State; recent_transitions: Transition[]; }
export interface Dataset { rows: Record<string, string | number>[]; daily: Metrics[]; current: Metrics; quality: Quality; state: State; registry: Factor[]; }
export interface LibraryComponent { name: string; label: string; description: string; source_file: string; output: unknown; implemented: boolean; }
export interface CompanyEvidence { id:string;period:string;metric:string;value:Num;previous:Num;unit:string;kind:string;note:string;source_title:string;source_url:string;page:number|null;published:string;retrieval_score?:number; }
export interface CompanyProfile { company:string;stock_code:string;verified_on:string;boundary:string;records:CompanyEvidence[]; }
export interface AccessInfo { mode:'lan'|'public'|'unavailable';share_url:string|null;lan_url:string|null;local_url:string;description:string; }
