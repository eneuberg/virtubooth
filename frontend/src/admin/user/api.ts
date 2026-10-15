/**
 * The user page's own writes (the shared ones live in store/actions.ts).
 */
import type { QueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { AdminUser } from '@/api/types';
import { patchUsers } from '../store/applyEvent';
import { call } from '../store/api';
import { qk } from '../store/keys';

/** DELETE /api/admin/users/{id}/display-name: the guest's display name back to the default. */
export async function resetDisplayName(qc: QueryClient, userId: number): Promise<AdminUser> {
  const res = await call(
    api.DELETE('/api/admin/users/{user_id}/display-name', { params: { path: { user_id: userId } } }),
  );
  patchUsers(qc, [res.user]);
  void qc.invalidateQueries({ queryKey: qk.user(userId) });
  return res.user;
}
