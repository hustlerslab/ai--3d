"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getJob, isTerminal } from "../api/projects-api";
import { ProjectsApiError, type EventDto, type JobDto } from "../types";

/**
 * Runs one pipeline job and polls it to completion.
 *
 * `run(start)` calls `start()` (which enqueues on the backend and returns the
 * job), then polls GET /jobs/{id} with a gentle backoff (1 s → 3 s) until the
 * job is terminal. Events come back with the job, so the progress panel needs
 * no second feed. Unmounting stops the polling; the job itself keeps running
 * on the backend and can be picked up again by id.
 */
export interface UseJobResult {
  job: JobDto | null;
  events: EventDto[];
  running: boolean;
  error: string | null;
  run: (start: () => Promise<JobDto>) => Promise<JobDto | null>;
  attach: (jobId: string) => Promise<JobDto | null>;
  reset: () => void;
}

export function useJob(): UseJobResult {
  const [job, setJob] = useState<JobDto | null>(null);
  const [events, setEvents] = useState<EventDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const alive = useRef(true);
  const polling = useRef<string | null>(null);
  useEffect(() => {
    // React StrictMode and Fast Refresh run cleanup + effect again on the same
    // instance, so "alive" must be re-armed here, not only set false below.
    alive.current = true;
    return () => {
      alive.current = false;
      polling.current = null;
    };
  }, []);

  const poll = useCallback(async (jobId: string): Promise<JobDto | null> => {
    let delay = 1000;
    polling.current = jobId;
    for (;;) {
      if (!alive.current || polling.current !== jobId) return null;
      let data: { job: JobDto; events: EventDto[] };
      try {
        data = await getJob(jobId);
      } catch (err) {
        if (!alive.current) return null;
        // transient network blip: keep polling a little longer before giving up
        if (err instanceof ProjectsApiError && err.status === 0) {
          await new Promise((r) => setTimeout(r, delay));
          delay = Math.min(delay * 1.5, 5000);
          continue;
        }
        setError(err instanceof Error ? err.message : String(err));
        setRunning(false);
        return null;
      }
      if (!alive.current) return null;
      setJob(data.job);
      setEvents(data.events);
      if (isTerminal(data.job.status)) {
        setRunning(false);
        if (data.job.status === "FAILED") setError(data.job.error || "The job failed.");
        return data.job;
      }
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 1.4, 3000);
    }
  }, []);

  const run = useCallback(
    async (start: () => Promise<JobDto>) => {
      setError(null);
      setRunning(true);
      setEvents([]);
      let started: JobDto;
      try {
        started = await start();
      } catch (err) {
        if (!alive.current) return null;
        setError(err instanceof Error ? err.message : String(err));
        setRunning(false);
        return null;
      }
      setJob(started);
      return poll(started.job_id);
    },
    [poll],
  );

  const attach = useCallback(
    async (jobId: string) => {
      setError(null);
      setRunning(true);
      return poll(jobId);
    },
    [poll],
  );

  const reset = useCallback(() => {
    polling.current = null;
    setJob(null);
    setEvents([]);
    setError(null);
    setRunning(false);
  }, []);

  // If a remount killed the poll while a job was still in flight, pick it up
  // again: the job kept running on the backend.
  useEffect(() => {
    if (job && !isTerminal(job.status) && polling.current !== job.job_id) {
      void attach(job.job_id);
    }
  }, [job, attach]);

  return { job, events, running, error, run, attach, reset };
}
