export type Project = { id: string; name: string; dataset_module?: string };
export type Message = {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  reasoning?: string;
  model?: string;
  created_at?: string;
  duration_seconds?: number;
  data?: unknown;
  request_id?: string;
};
export type Chat = {
  id: string;
  project_id: string;
  name: string;
  messages?: Message[];
  active_job?: string;
  model_id?: string;
  effort?: string;
};
export type Source = {
  id: string;
  project_id: string;
  provider: string;
  name: string;
  connected: boolean;
  remembered?: boolean;
  metadata: Record<string, string>;
};
export type Model = {
  id: string;
  name: string;
  provider: string;
  model_id: string;
  connected: boolean;
  available?: boolean;
  system?: boolean;
  efforts: string[];
};
export type ProviderField = {
  key: string;
  label: string;
  secret: boolean;
  kind: string;
  placeholder: string;
  help: string;
  options?: string[];
};
export type Provider = {
  id: string;
  name: string;
  color: string;
  description: string;
  docs: string;
  fields: ProviderField[];
  reports: string[];
};
export type Workspace = {
  csrf_token: string;
  projects: Project[];
  chats: Chat[];
  sources: Source[];
  models: Model[];
  providers: Provider[];
  model_providers: { id: string; name: string; base_url: string }[];
  default_period: { date1: string; date2: string };
  active_jobs: { id: string; chat_id: string }[];
};
export type Job = {
  id: string;
  status: string;
  error?: string;
  events: { type: string; text: string; state?: string; at: string }[];
  result?: Message;
};
export type Report = {
  metrics?: { key: string; label: string; value: number; format: string }[];
  series?: Record<string, number | string | null>[];
  rows?: Record<string, unknown>[];
  columns?: string[];
  total_rows?: number;
  date1: string;
  date2: string;
  sampled?: boolean;
  sample_share?: number;
  cached?: boolean;
  fetched_at?: string;
  limited?: boolean;
  has_more?: boolean;
  page?: number;
  note?: string;
};
