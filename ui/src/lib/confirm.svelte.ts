/** In-app replacement for window.confirm(), rendered by ConfirmDialog. */
export type Ask = { message: string; action: string; resolve: (ok: boolean) => void };

export const dialog = $state<{ ask: Ask | null }>({ ask: null });

/** Ask the user to confirm a destructive action; resolves true on confirm. */
export function confirmAction(message: string, action = "Delete"): Promise<boolean> {
  dialog.ask?.resolve(false);
  return new Promise((resolve) => { dialog.ask = { message, action, resolve }; });
}

export function answer(ok: boolean) {
  const a = dialog.ask;
  dialog.ask = null;
  a?.resolve(ok);
}
