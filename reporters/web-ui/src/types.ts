export interface HostInfo {
  hostname: string;
  instance_id: string;
  instance_type: string;
  region: string;
  uptime_seconds: number;
}

export interface Report {
  timestamp: string;
  host: HostInfo;
  cpu: {
    usage_percent: number;
    cores: number;
    load_avg: number[];
    steal_percent: number;
  };
  memory: {
    used_percent: number;
    used_bytes: number;
    total_bytes: number;
    oom_kills: number;
  };
  disks: Array<{
    mount: string;
    used_percent: number;
    used_bytes: number;
    total_bytes: number;
    days_until_full: number | null;
  }>;
  processes: Array<{
    name: string;
    status: string;
    pid: number | null;
    cpu_percent: number | null;
    memory_mb: number | null;
  }>;
  ports: Array<{
    port: number;
    service: string;
    status: string;
    response_ms: number | null;
  }>;
  log_matches: Array<{
    pattern: string;
    count: number;
    file: string;
  }>;
}

export interface Alert {
  severity: "warning" | "critical";
  title: string;
  message: string;
}

export interface Verdict {
  status: "ok" | "warning" | "critical";
  warnings: string[];
  criticals: string[];
}

export interface HostPayload {
  source: string;
  filename?: string;
  report: Report;
  alerts?: Alert[];
  verdict?: Verdict;
}

export interface HealthPayload {
  live: HostPayload;
  fleet: HostPayload[];
  thresholds: Record<string, number>;
  refresh_seconds: number;
}
