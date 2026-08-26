/**
 * usePlan — tier-aware plan state hook.
 *
 * plan = "free" | "paid" | "pro" | "studio" | "enterprise"
 *   isPaid       — plan >= "paid"
 *   isPro        — plan >= "pro"
 *   isStudio     — plan >= "studio"
 *   isEnterprise — plan >= "enterprise"
 *
 * Admin emails always get "enterprise".
 * Compatible with existing usePaywall consumers — exposes unlock/lock shortcuts.
 */

import { useState, useCallback, useEffect } from 'react';
import { loadPlan, savePlan, meetsPlan } from '../data/planStore';

import { isAdminEmail } from '../config/admin';

export default function usePlan(userEmail) {
  const isAdmin = isAdminEmail(userEmail);
  const [plan, setPlanState] = useState(() => isAdmin ? 'enterprise' : loadPlan());

  useEffect(() => {
    if (isAdmin) {
      savePlan('enterprise');
      setPlanState('enterprise');
    }
  }, [isAdmin]);

  // Cross-component sync: when another usePlan instance writes to localStorage,
  // this instance picks up the change. Also handles custom 'ngw_plan_change'
  // events for same-tab sync (storage events only fire cross-tab).
  useEffect(() => {
    const sync = () => setPlanState(loadPlan());
    window.addEventListener('storage', sync);
    window.addEventListener('ngw_plan_change', sync);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener('ngw_plan_change', sync);
    };
  }, []);

  const setPlan = useCallback((p, { force = false } = {}) => {
    if (isAdmin && !force) return;
    savePlan(p);
    setPlanState(p);
    // Dispatch custom event for same-tab sync
    window.dispatchEvent(new Event('ngw_plan_change'));
  }, [isAdmin]);

  const isPaid       = meetsPlan(plan, 'paid');
  const isPro        = meetsPlan(plan, 'pro');
  const isStudio     = meetsPlan(plan, 'studio');
  const isEnterprise = meetsPlan(plan, 'enterprise');

  // Backward-compat shortcuts (mirrors usePaywall API)
  const unlock = useCallback(() => setPlan('paid'), [setPlan]);
  const lock   = useCallback(() => setPlan('free'), [setPlan]);

  return { plan, setPlan, isPaid, isPro, isStudio, isEnterprise, isAdmin, unlock, lock };
}
