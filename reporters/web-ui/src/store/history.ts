import { create } from "zustand";

export interface SamplePoint {
  t: number;
  cpu: number;
  memory: number;
  load: number;
  iowait: number;
  steal: number;
}

const MAX_POINTS = 40;

interface HistoryState {
  points: SamplePoint[];
  push: (sample: Omit<SamplePoint, "t">) => void;
  clear: () => void;
}

export const useHistoryStore = create<HistoryState>((set) => ({
  points: [],
  push: (sample) =>
    set((state) => ({
      points: [...state.points, { ...sample, t: Date.now() }].slice(-MAX_POINTS),
    })),
  clear: () => set({ points: [] }),
}));
