/**
 * B2. Состояние конструктора: блоки, тема сайта, автосохранение черновика, undo.
 *
 * Пользователь редактирует локальную копию content_json; изменения улетают на
 * backend с задержкой (автосохранение), чтобы каждый ввод символа не рождал запрос.
 */
import { create } from "zustand";
import { ApiError } from "../api/client";
import { sitesApi } from "../api/endpoints";
import type { Block, BlockType, Site, SiteContent } from "../api/types";
import { createBlock } from "../templates/catalog";

const AUTOSAVE_DELAY = 1200;
const HISTORY_LIMIT = 50;

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

interface EditorState {
  site: Site | null;
  content: SiteContent | null;
  title: string;
  saveState: SaveState;
  /** Текст последней ошибки автосохранения — чтобы не показывать немой красный бейдж. */
  saveError: string | null;
  /** Сайт удалён на сервере: сохранять больше некуда, автосохранение выключено. */
  siteMissing: boolean;
  selectedBlockId: string | null;
  history: SiteContent[];
  future: SiteContent[];

  load: (site: Site) => void;
  reset: () => void;
  /** Сброс, если в редакторе открыт именно этот сайт (например, его удалили из списка). */
  discardIfLoaded: (siteId: string) => void;
  select: (blockId: string | null) => void;

  setTitle: (title: string) => void;
  updateContent: (updater: (content: SiteContent) => SiteContent) => void;
  updateBlock: (blockId: string, props: Record<string, unknown>) => void;
  addBlock: (type: BlockType) => void;
  removeBlock: (blockId: string) => void;
  moveBlock: (blockId: string, direction: -1 | 1) => void;
  toggleBlock: (blockId: string) => void;

  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;

  saveNow: () => Promise<void>;
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

function clone(content: SiteContent): SiteContent {
  return JSON.parse(JSON.stringify(content)) as SiteContent;
}

export const useEditorStore = create<EditorState>((set, get) => {
  function scheduleSave(): void {
    if (saveTimer) clearTimeout(saveTimer);
    // сайта на сервере уже нет — новые попытки дадут те же 404
    if (get().siteMissing) return;
    set({ saveState: "dirty" });
    saveTimer = setTimeout(() => {
      void get().saveNow();
    }, AUTOSAVE_DELAY);
  }

  function pushHistory(): void {
    const { content, history } = get();
    if (!content) return;
    set({
      history: [...history, clone(content)].slice(-HISTORY_LIMIT),
      future: [],
    });
  }

  return {
    site: null,
    content: null,
    title: "",
    saveState: "idle",
    saveError: null,
    siteMissing: false,
    selectedBlockId: null,
    history: [],
    future: [],

    load(site) {
      if (saveTimer) clearTimeout(saveTimer);
      set({
        site,
        content: clone(site.content_json),
        title: site.title,
        saveState: "idle",
        saveError: null,
        siteMissing: false,
        selectedBlockId: null,
        history: [],
        future: [],
      });
    },

    reset() {
      if (saveTimer) clearTimeout(saveTimer);
      set({
        site: null,
        content: null,
        title: "",
        saveState: "idle",
        saveError: null,
        siteMissing: false,
        history: [],
        future: [],
      });
    },

    discardIfLoaded(siteId) {
      if (get().site?.id === siteId) get().reset();
    },

    select(blockId) {
      set({ selectedBlockId: blockId });
    },

    setTitle(title) {
      set({ title });
      scheduleSave();
    },

    updateContent(updater) {
      const { content } = get();
      if (!content) return;
      pushHistory();
      set({ content: updater(clone(content)) });
      scheduleSave();
    },

    updateBlock(blockId, props) {
      get().updateContent((content) => ({
        ...content,
        blocks: content.blocks.map((block) =>
          block.id === blockId ? { ...block, props: { ...block.props, ...props } } : block,
        ),
      }));
    },

    addBlock(type) {
      const block = createBlock(type);
      get().updateContent((content) => ({ ...content, blocks: [...content.blocks, block] }));
      set({ selectedBlockId: block.id });
    },

    removeBlock(blockId) {
      get().updateContent((content) => ({
        ...content,
        blocks: content.blocks.filter((block) => block.id !== blockId),
      }));
      if (get().selectedBlockId === blockId) set({ selectedBlockId: null });
    },

    moveBlock(blockId, direction) {
      get().updateContent((content) => {
        const blocks: Block[] = [...content.blocks];
        const index = blocks.findIndex((b) => b.id === blockId);
        const target = index + direction;
        if (index < 0 || target < 0 || target >= blocks.length) return content;
        [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
        return { ...content, blocks };
      });
    },

    toggleBlock(blockId) {
      get().updateContent((content) => ({
        ...content,
        blocks: content.blocks.map((block) =>
          block.id === blockId ? { ...block, hidden: !block.hidden } : block,
        ),
      }));
    },

    undo() {
      const { history, content, future } = get();
      if (!history.length || !content) return;
      const previous = history[history.length - 1];
      set({
        content: previous,
        history: history.slice(0, -1),
        future: [clone(content), ...future].slice(0, HISTORY_LIMIT),
      });
      scheduleSave();
    },

    redo() {
      const { future, content, history } = get();
      if (!future.length || !content) return;
      const [next, ...rest] = future;
      set({
        content: next,
        future: rest,
        history: [...history, clone(content)].slice(-HISTORY_LIMIT),
      });
      scheduleSave();
    },

    canUndo: () => get().history.length > 0,
    canRedo: () => get().future.length > 0,

    async saveNow() {
      const { site, content, title } = get();
      if (!site || !content) return;
      if (saveTimer) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
      if (get().siteMissing) return;
      set({ saveState: "saving" });
      try {
        const { site: saved } = await sitesApi.update(site.id, { title, content_json: content });
        set({ site: saved, saveState: "saved", saveError: null });
      } catch (error) {
        // сайт удалён (в другом окне или на другом устройстве) — сохранять некуда,
        // и повторять бессмысленно: без этого редактор молча долбился в 404
        const missing = error instanceof ApiError && error.status === 404;
        set({
          saveState: "error",
          siteMissing: missing,
          saveError: error instanceof Error ? error.message : String(error),
        });
      }
    },
  };
});
