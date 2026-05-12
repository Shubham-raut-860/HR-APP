import api from './api';

/**
 * Fetch job postings.
 * @param activeOnly - true (default) returns only active/open jobs.
 *   Pass false to include closed jobs — used by Dashboard to compute
 *   "all-time" activity feed entries across the full job history.
 */
export const getJobs = async (activeOnly = true, signal?: AbortSignal) => {
  const response = await api.get('/jd/', { params: { active_only: activeOnly }, signal });
  return response.data;
};

export const getJob = async (id: string, signal?: AbortSignal) => {
  const response = await api.get(`/jd/${id}`, { signal });
  return response.data;
};

export const createJob = async (data: any) => {
  const response = await api.post('/jd/', data);
  return response.data;
};

export const generateJob = async (data: any) => {
  const response = await api.post('/jd/generate', data);
  return response.data;
};

export const generateJobFromDocument = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/jd/from-document', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60_000,
  });
  return response.data;
};

/**
 * Upload multiple JD documents and auto-create one job per file.
 * Returns { success: [...], failed: [...], success_count, failed_count }
 */
export const bulkCreateJobsFromDocuments = async (
  files: File[],
  onProgress?: (done: number, total: number) => void,
) => {
  const formData = new FormData();
  files.forEach((f) => formData.append('files', f));
  const response = await api.post('/jd/bulk-from-documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300_000,   // 5 min — OCR on large PDFs can be slow
    onUploadProgress: (evt) => {
      if (onProgress && evt.total) {
        onProgress(evt.loaded, evt.total);
      }
    },
  });
  return response.data;
};

export const updateJob = async (id: string, data: any) => {
  const response = await api.put(`/jd/${id}`, data);
  return response.data;
};

export const deleteJob = async (id: string) => {
  const response = await api.delete(`/jd/${id}`);
  return response.data;
};

export const closeJob = async (id: string) => {
  const response = await api.patch(`/jd/${id}/close`);
  return response.data;
};
