import api from './api';

export interface Notification {
  id: string;
  title: string;
  message: string;
  type: string;
  is_read: boolean;
  is_dismissed: boolean;
  related_id: string | null;
  created_at: string;
}

export interface NotificationsResponse {
  notifications: Notification[];
  unread_count: number;
  is_snoozed: boolean;
  snooze_until: string | null;
}

export const getNotifications = async (): Promise<NotificationsResponse> => {
  const response = await api.get('/notifications/');
  return response.data;
};

export const markNotificationRead = async (id: string) => {
  const response = await api.put(`/notifications/${id}/read`);
  return response.data;
};

export const markAllRead = async () => {
  const response = await api.put('/notifications/read-all');
  return response.data;
};

export const dismissNotification = async (id: string) => {
  const response = await api.delete(`/notifications/${id}`);
  return response.data;
};

export const clearAllNotifications = async () => {
  const response = await api.delete('/notifications/');
  return response.data;
};

export const setSnooze = async (snoozeUntil: string | null) => {
  const response = await api.put('/notifications/preferences', { snooze_until: snoozeUntil ?? "" });
  return response.data;
};
