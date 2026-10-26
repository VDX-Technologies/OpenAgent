<script lang="ts">
  import { fmtNum } from "#lib/ui";

  type Day = { day: string; prompt_tokens: number; completion_tokens: number; requests: number };
  let { days }: { days: Day[] } = $props();

  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /** 53 week columns ending this week; each cell is one day (Sunday first). */
  const grid = $derived.by(() => {
    const byDay = new Map(days.map((d) => [d.day, d]));
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const start = new Date(today); start.setDate(start.getDate() - start.getDay() - 52 * 7);
    const max = Math.max(1, ...days.map((d) => d.prompt_tokens + d.completion_tokens));
    const weeks: { key: string; total: number; requests: number; level: number; future: boolean }[][] = [];
    const months: { col: number; label: string }[] = [];
    for (let w = 0; w < 53; w++) {
      const col = [];
      for (let i = 0; i < 7; i++) {
        const d = new Date(start); d.setDate(start.getDate() + w * 7 + i);
        const key = iso(d);
        const r = byDay.get(key);
        const total = r ? r.prompt_tokens + r.completion_tokens : 0;
        // sqrt scale: a few heavy days don't wash out the rest
        const level = total ? Math.min(4, 1 + Math.floor(Math.sqrt(total / max) * 3.999)) : 0;
        col.push({ key, total, requests: r?.requests ?? 0, level, future: d > today });
        if (i === 0 && d.getDate() <= 7) months.push({ col: w, label: MONTHS[d.getMonth()] });
      }
      weeks.push(col);
    }
    return { weeks, months };
  });
</script>

<div class="overflow-x-auto">
  <div class="inline-flex flex-col gap-1.5">
    <div class="relative h-3 text-[10px] text-[var(--text-dim)]" style:margin-left="26px">
      {#each grid.months as m (m.col)}<span class="absolute" style:left="{m.col * 13}px">{m.label}</span>{/each}
    </div>
    <div class="flex gap-1">
      <div class="grid grid-rows-7 gap-[3px] pr-1 text-[10px] leading-[10px] text-[var(--text-dim)]">
        {#each ["", "Mon", "", "Wed", "", "Fri", ""] as l, i (i)}<span class="h-[10px]">{l}</span>{/each}
      </div>
      <div class="flex gap-[3px]">
        {#each grid.weeks as col, w (w)}
          <div class="flex flex-col gap-[3px]">
            {#each col as c (c.key)}
              <div class="cell lv{c.level}" class:invisible={c.future}
                title="{c.key}: {c.total ? `${fmtNum(c.total)} tokens · ${c.requests} requests` : 'no activity'}"></div>
            {/each}
          </div>
        {/each}
      </div>
    </div>
    <div class="flex items-center justify-end gap-1 text-[10px] text-[var(--text-dim)]">
      Less {#each [0, 1, 2, 3, 4] as l (l)}<div class="cell lv{l}"></div>{/each} More
    </div>
  </div>
</div>

<style>
  .cell { width: 10px; height: 10px; border-radius: 2.5px; }
  .lv0 { background: var(--bg-hover); }
  .lv1 { background: color-mix(in srgb, var(--accent) 25%, var(--bg-hover)); }
  .lv2 { background: color-mix(in srgb, var(--accent) 50%, var(--bg-hover)); }
  .lv3 { background: color-mix(in srgb, var(--accent) 75%, var(--bg-hover)); }
  .lv4 { background: var(--accent); }
</style>
