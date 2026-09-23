/** Jev Choice allows 255 options. The app always adds reserved `other`, so a task may select at most 254 custom tags. */
export const MAX_TASK_TAGS = 254;

/**
 * Unchecked tags lock once the selection reaches the cap.
 * Checked tags stay enabled so an over-cap task loaded from older data can be reduced.
 */
export function tagPickDisabled(checked: boolean, selectedCount: number, cap = MAX_TASK_TAGS): boolean {
  return !checked && selectedCount >= cap;
}
