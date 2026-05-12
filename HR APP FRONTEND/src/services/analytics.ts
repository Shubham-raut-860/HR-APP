import api from './api';
import { assertBlobResponseSuccess, throwBlobRequestError } from './blobError';

export const getSummary = async (jobId: string, signal?: AbortSignal) => {
  const response = await api.get(`/analytics/summary/${jobId}`, { signal });
  return response.data;
};

export const getUntaggedMetrics = async (signal?: AbortSignal) => {
  const response = await api.get('/analytics/metrics/untagged', { signal });
  return response.data;
};

export const getRankings = async (jobId: string, recalculate = false) => {
  const response = await api.get(`/analytics/rankings/${jobId}`, {
    params: { recalculate },
  });
  return response.data;
};

export const getSkillGap = async (jobId: string) => {
  const response = await api.get(`/analytics/skill-gap/${jobId}`);
  return response.data;
};

export const calculateRankings = async (jobId: string) => {
  const response = await api.post(`/analytics/rank/${jobId}`);
  return response.data;
};

export const exportExcel = async (jobId: string) => {
  try {
    // Export operations can exceed default request timeouts on large datasets.
    const response = await api.get(`/analytics/export/excel/${jobId}`, {
      responseType: 'blob',
      timeout: 300_000,
    });
    const blob: Blob = response.data;
    await assertBlobResponseSuccess(blob, 'Excel export failed.');

    const downloadBlob = blob.type
      ? blob
      : new Blob([blob], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        });
    const url = window.URL.createObjectURL(downloadBlob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `report_${jobId}.xlsx`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (error) {
    await throwBlobRequestError(error, 'Excel export failed.');
  }
};

export const exportPDF = async (jobId: string) => {
  try {
    const response = await api.get(`/analytics/export/pdf/${jobId}`, {
      responseType: 'blob',
      timeout: 300_000,
    });
    const blob: Blob = response.data;
    await assertBlobResponseSuccess(blob, 'PDF export failed.');

    const downloadBlob = blob.type ? blob : new Blob([blob], { type: 'application/pdf' });
    const url = window.URL.createObjectURL(downloadBlob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `report_${jobId}.pdf`);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  } catch (error) {
    await throwBlobRequestError(error, 'PDF export failed.');
  }
};
