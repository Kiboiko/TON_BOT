/**
 * B2. Состояние конструктора: блоки, тема сайта, автосохранение черновика, undo.
 *
 * Пользователь редактирует локальную копию content_json; изменения улетают на
 * backend с задержкой (автосохранение), чтобы каждый ввод символа не рождал запрос.
 */
import { create } from "zustand";
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
  selectedBlockId: string | null;
  history: SiteContent[];
  future: SiteContent[];

  load: (site: Site) => void;
  reset: () => void;
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
        selectedBlockId: null,
        history: [],
        future: [],
      });
    },

    reset() {
      if (saveTimer) clearTimeout(saveTimer);
      set({ site: null, content: null, title: "", saveState: "idle", history: [], future: [] });
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
      set({ saveState: "saving" });
      try {
        const { site: saved } = await sitesApi.update(site.id, { title, content_json: content });
        set({ site: saved, saveState: "saved" });
      } catch {
        set({ saveState: "error" });
      }
    },
  };
});
