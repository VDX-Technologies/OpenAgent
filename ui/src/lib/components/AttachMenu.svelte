<script lang="ts" module>
  /** One thing attached to the next message: an image (data URL), a web page URL or a chat id. */
  export type Attached = { kind: "image" | "url" | "chat"; value: string; label: string };
</script>

<script lang="ts">
  import { listConversations, type Conversation } from "#lib/api";

  let { items = $bindable([]) }: { items: Attached[] } = $props();

  const MAX_IMAGES = 4, MAX_URLS = 5, MAX_CHATS = 5, MAX_SIDE = 1568;

  let open = $state(false);
  let mode = $state<"menu" | "url" | "chat">("menu");
  let url = $state("");
  let query = $state("");
  let chats = $state<Conversation[]>([]);
  let fileInput: HTMLInputElement;

  const count = (kind: Attached["kind"]) => items.filter((a) => a.kind === kind).length;

  function close() { open = false; mode = "menu"; url = ""; query = ""; }

  /** Read an image file and downscale it so the request stays small. */
  function toDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const src = URL.createObjectURL(file);
      img.onload = () => {
        const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(src);
        resolve(canvas.toDataURL("image/jpeg", 0.88));
      };
      img.onerror = () => { URL.revokeObjectURL(src); reject(new Error("Unreadable image")); };
      img.src = src;
    });
  }

  async function addImages(files: FileList | null) {
    for (const f of Array.from(files ?? [])) {
      if (!f.type.startsWith("image/") || count("image") >= MAX_IMAGES) continue;
      try { items.push({ kind: "image", value: await toDataUrl(f), label: f.name }); } catch { /* skip */ }
    }
    fileInput.value = "";
    close();
  }

  function addUrl() {
    let u = url.trim();
    if (!u || count("url") >= MAX_URLS) return;
    if (!/^https?:\/\//i.test(u)) u = `https://${u}`;
    items.push({ kind: "url", value: u, label: u.replace(/^https?:\/\//i, "") });
    close();
  }

  async function loadChats() {
    try { chats = (await listConversations(query)).conversations; } catch { chats = []; }
  }

  function addChat(c: Conversation) {
    if (count("chat") < MAX_CHATS && !items.some((a) => a.kind === "chat" && a.value === String(c.id)))
      items.push({ kind: "chat", value: String(c.id), label: c.title });
    close();
  }
</script>

<svelte:window onclick={close} />

<input bind:this={fileInput} type="file" accept="image/*" multiple class="hidden"
  onchange={(e) => addImages(e.currentTarget.files)} />

<div class="relative">
  <button type="button" title="Attach" onclick={(e) => { e.stopPropagation(); open ? close() : (open = true); }}
    class="flex h-7 w-7 items-center justify-center rounded-full border border-[var(--border)] text-[15px] text-[var(--text-muted)] hover:text-[var(--text)]">
    +
  </button>
  {#if open}
    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
    <div onclick={(e) => e.stopPropagation()}
      class="vdx-popover absolute bottom-full left-0 z-30 mb-2 w-72 rounded-xl border border-[var(--border-strong)] bg-[var(--bg-panel)] p-1 shadow-2xl">
      {#if mode === "menu"}
        <button type="button" disabled={count("image") >= MAX_IMAGES} onclick={() => fileInput.click()}
          class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)] disabled:opacity-40">
          🖼 Upload image
        </button>
        <button type="button" disabled={count("url") >= MAX_URLS} onclick={() => (mode = "url")}
          class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)] disabled:opacity-40">
          🔗 Attach web page
        </button>
        <button type="button" disabled={count("chat") >= MAX_CHATS} onclick={() => { mode = "chat"; loadChats(); }}
          class="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-[12.5px] hover:bg-[var(--bg-hover)] disabled:opacity-40">
          💬 Reference a chat
        </button>
      {:else if mode === "url"}
        <form class="flex gap-1.5 p-1.5" onsubmit={(e) => { e.preventDefault(); addUrl(); }}>
          <!-- svelte-ignore a11y_autofocus -->
          <input bind:value={url} autofocus placeholder="https://example.com"
            class="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-2 py-1 text-[12.5px] outline-none focus:border-[var(--border-strong)]" />
          <button type="submit" class="ghost-btn !text-[12px]">Add</button>
        </form>
      {:else}
        <div class="p-1.5">
          <!-- svelte-ignore a11y_autofocus -->
          <input bind:value={query} oninput={loadChats} autofocus placeholder="Search chats"
            class="w-full rounded-lg border border-[var(--border)] bg-transparent px-2 py-1 text-[12.5px] outline-none focus:border-[var(--border-strong)]" />
        </div>
        <div class="max-h-60 overflow-y-auto">
          {#each chats as c (c.id)}
            <button type="button" onclick={() => addChat(c)}
              class="block w-full truncate rounded-lg px-3 py-1.5 text-left text-[12.5px] hover:bg-[var(--bg-hover)]">{c.title}</button>
          {:else}
            <p class="px-3 py-2 text-[12px] text-[var(--text-dim)]">No chats found</p>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
