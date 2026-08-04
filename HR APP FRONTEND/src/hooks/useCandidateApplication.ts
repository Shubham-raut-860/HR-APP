import { useCallback } from "react";
import { getMyResults } from "@/services/candidatePortal";
import api from "@/services/api";

type StepStatus = "waiting" | "passed" | "failed" | "current";

export function useCandidateApplication() {
  const evaluateResume = useCallback(async (jobId: string, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await api.post(`/candidate/evaluate-resume/${jobId}`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data;
  }, []);

  const getMyApplication = useCallback(async (jobId: string) => {
    const results = await getMyResults();
    return results.find((r: any) => r.job_id === jobId) ?? null;
  }, []);

  const getStepStatus = useCallback((myApp: any, stepIndex: number): StepStatus => {
    if (!myApp) return "waiting";
    if (stepIndex === 0) {
      if (["Strong", "Medium"].includes(myApp.tag)) return "passed";
      if (myApp.tag === "Reject") return "failed";
      return "current";
    }
    if (stepIndex === 1) {
      if (myApp.tag === "Reject") return "waiting";
      if (myApp.passed === true) return "passed";
      if (myApp.passed === false && myApp.quiz_status === "submitted") return "failed";
      if (myApp.quiz_status === "pending" || myApp.quiz_status === "in_progress") return "current";
      return "waiting";
    }
    if (stepIndex === 2) {
      if (myApp.passed === true) return "current";
      return "waiting";
    }
    return "waiting";
  }, []);

  return { evaluateResume, getMyApplication, getStepStatus };
}
