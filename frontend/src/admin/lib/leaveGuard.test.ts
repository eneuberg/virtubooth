import { describe, expect, it, vi } from 'vitest';
import { guardedNavigate, setLeaveGuard } from './leaveGuard';

describe('leaveGuard', () => {
  it('runs the navigation at once without a guard', () => {
    const go = vi.fn();
    guardedNavigate(go);
    expect(go).toHaveBeenCalledOnce();
  });

  it('hands the navigation to the guard, which may go on later', () => {
    let held: (() => void) | null = null;
    const remove = setLeaveGuard((proceed) => {
      held = proceed;
      return true;
    });
    const go = vi.fn();
    guardedNavigate(go);
    expect(go).not.toHaveBeenCalled();
    expect(held).toBe(go);
    remove();
    guardedNavigate(go);
    expect(go).toHaveBeenCalledOnce();
  });

  it('a guard that lets go, and removing an old guard keeps the newer one', () => {
    const removeOld = setLeaveGuard(() => true);
    const removeNew = setLeaveGuard(() => false);
    removeOld();
    const go = vi.fn();
    guardedNavigate(go);
    expect(go).toHaveBeenCalledOnce();
    removeNew();
  });
});
