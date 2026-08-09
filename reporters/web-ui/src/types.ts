export interface HostInfo {
  hostname: string;
  instance_id: string;
  instance_type: string;
  region: string;
  uptime_seconds: number;
}

export interface TopProcess {
  pid: number;
  name: string;
  cmdline: string;
  cpu_percent: number;
  memory_mb: number;
  memory_percent: number;
}

export interface Finding {
  severity: "ok" | "info" | "warning" | "critical";
  category: string;
  title: string;
  what: string;
  why_it_matters: string;
  say_this: string;
  next_step: string;
}

export interface Diagnosis {
  headline: string;
  summary: string;
  health: "healthy" | "degraded" | "critical";
  cpu_story: string;
  memory_story: string;
  talk_track: string[];
  findings: Finding[];
}

export interface Report {
  timestamp: string;
  host: HostInfo;
  cpu: {
    usage_percent: number;
    cores: number;
    load_avg: number[];
    steal_percent: number;
    user_percent?: number;
    system_percent?: number;
    iowait_percent?: number;
    idle_percent?: number;
    irq_percent?: number;
    load_per_core?: number;
  };
  memory: {
    used_percent: number;
    used_bytes: number;
    total_bytes: number;
    available_bytes?: number;
    available_percent?: number;
    swap_used_percent: number;
    swap_used_bytes?: number;
    oom_kills: number;
    app_bytes?: number;
    cached_bytes?: number;
    buffers_bytes?: number;
    free_bytes?: number;
  };
  disks: Array<{
    mount: string;
    used_percent: number;
    used_bytes: number;
    total_bytes: number;
    days_until_full: number | null;
  }>;
  top?: {
    by_cpu: TopProcess[];
    by_memory: TopProcess[];
    sample_seconds: number;
  };
  diagnosis?: Diagnosis;
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
  docker?: {
    available: boolean;
    server_version: string;
    error: string;
    running_count: number;
    stopped_count: number;
    image_count: number;
    disk: {
      images_size: string;
      images_reclaimable: string;
      containers_size: string;
      containers_reclaimable: string;
      volumes_size: string;
      volumes_reclaimable: string;
      build_cache_reclaimable: string;
    };
    containers: Array<{
      id: string;
      name: string;
      image: string;
      state: string;
      status: string;
      ports: string;
      health: string | null;
    }>;
    images: Array<{
      repository: string;
      tag: string;
      id: string;
      size: string;
      created_since: string;
    }>;
  };
  java?: {
    enabled: boolean;
    available: boolean;
    error: string;
    java_home: string | null;
    default_java: string | null;
    installation_count: number;
    jdk_count: number;
    installations: Array<{
      path: string;
      version: string;
      vendor: string;
      runtime_name: string;
      raw_version: string;
      is_jdk: boolean;
      javac_version: string | null;
      display: string;
    }>;
    processes: Array<{
      pid: number;
      name: string;
      java_path: string | null;
      version: string | null;
      cmdline: string;
    }>;
  };
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
