<script lang="ts">
  /** On/off switch visual (the clickable element is the parent). Knob contrasts with the track in both themes. */
  let { on, size = "md" }: { on: boolean; size?: "sm" | "md" } = $props();
  const s = $derived(size === "sm" ? { track: "h-3.5 w-6", knob: "h-2.5 w-2.5", move: "translate-x-2.5" } : { track: "h-4 w-7", knob: "h-3 w-3", move: "translate-x-3" });
</script>

<span aria-hidden="true"
  class="inline-flex shrink-0 items-center rounded-full p-0.5 transition-colors {s.track} {on ? 'bg-[var(--accent)]' : 'bg-[var(--border-strong)]'}">
  <span class="rounded-full shadow-sm transition-transform duration-150 {s.knob} {on ? `${s.move} bg-[var(--accent-text)]` : 'translate-x-0 bg-white'}"></span>
</span>
