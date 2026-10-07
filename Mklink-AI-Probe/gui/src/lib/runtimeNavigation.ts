/** A probe handoff must discard the old device's module/socket state. */
let navigating = false
export function navigateToRuntime(href = window.location.href): void {
  // HTTP selection and the old presence socket can announce the same switch.
  if (navigating) return
  const target = new URL(href, window.location.href)
  target.searchParams.set('runtime_transition', 'probe')
  navigating = true
  window.location.replace(target.href)
}
