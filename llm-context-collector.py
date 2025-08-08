import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import pathlib
import threading
import queue
import json
import re
from datetime import datetime
import difflib

try:
    import gitignore_parser
    gitignore_parser_available = True
except ImportError:
    gitignore_parser = None
    gitignore_parser_available = False

DEFAULT_EXTENSIONS = [
    ".razor", ".cs", ".js", ".css", ".html", ".cshtml",
    ".json", ".xml", ".txt", ".md"
]
DEFAULT_IGNORE_PATTERNS = [
    "node_modules", "vendor", "dist", "build", "target", "__pycache__",
    "bin", "obj",
    ".git", ".svn", ".hg", ".idea", ".vscode",
    "*.pyc", "*.pyo", "*.class", "*.o", "*.obj", "*.dll", "*.so", "*.exe",
    ".DS_Store"
]
CHARS_PER_TOKEN_ESTIMATE = 4
HISTORY_LIMIT = 30
HISTORY_FILENAME = ".llm_context_collector_history.json"
PROMPT_FILENAME = ".llm_context_prompts.json"
PREVIEW_MAX_CHARS = 10000

CSHARP_KEYWORDS_REGEX = r'\b(public|private|protected|internal|static|class|struct|interface|enum|void|string|int|bool|double|float|decimal|long|short|byte|var|get|set|new|using|namespace|return|if|else|for|foreach|while|do|switch|case|default|break|continue|try|catch|finally|throw|lock|using|yield|base|this|true|false|null|async|await|partial|readonly|virtual|override|sealed|abstract|as|is|in|out|ref|params|checked|unchecked|unsafe|fixed|stackalloc)\b'
CSHARP_COMMON_TYPES_REGEX = r'\b(object|string|int|bool|double|float|decimal|long|short|byte|List|Dictionary|IEnumerable|Task|IActionResult|ICollection|Exception|PageModel|ComponentBase|DbContext|WebApplication|Program|HttpContext|IServiceCollection|IConfiguration|ILogger|Activator|Attribute|EventArgs|Console|Math|DateTime|Guid|CancellationToken|TaskCompletionSource|Action|Func|Predicate|Tuple|ValueTuple)\b'
POTENTIAL_TYPE_REGEX = r'\b[A-Z][a-zA-Z0-9_]*\b(?:<[A-Za-z0-9_,\s<>]+>)?'


class DiffWindow(tk.Toplevel):
    def __init__(self, parent, global_explanation, diff_results, project_root):
        super().__init__(parent)
        self.title("Változások Elemzése és Elfogadása")
        self.geometry("1200x800")
        self.transient(parent)
        self.grab_set()

        self.diff_results = diff_results
        self.project_root = pathlib.Path(project_root)
        self.global_explanation = global_explanation
        self.view_mode = tk.StringVar(value="diff")

        main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_frame = ttk.Frame(main_pane, padding=(0, 0, 5, 0))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)
        main_pane.add(left_frame, weight=3)
        
        ttk.Label(left_frame, text="Feldolgozott fájlok:", font="-weight bold").grid(row=0, column=0, sticky="w", pady=(0,5))
        
        list_container = ttk.Frame(left_frame)
        list_container.grid(row=1, column=0, sticky="nsew")
        list_container.rowconfigure(0, weight=1)
        list_container.columnconfigure(0, weight=1)

        self.file_listbox = tk.Listbox(list_container, selectmode=tk.EXTENDED)
        self.file_listbox.grid(row=0, column=0, sticky="nsew")
        list_ysb = ttk.Scrollbar(list_container, orient='vertical', command=self.file_listbox.yview)
        list_ysb.grid(row=0, column=1, sticky='ns')
        self.file_listbox.configure(yscrollcommand=list_ysb.set)
        self.file_listbox.bind("<<ListboxSelect>>", self._on_file_select)

        right_frame = ttk.Frame(main_pane)
        right_frame.columnconfigure(0, weight=1)
        main_pane.add(right_frame, weight=5)

        row_idx = 0
        if self.global_explanation:
            explanation_frame = ttk.LabelFrame(right_frame, text="Globális Magyarázat", padding=5)
            explanation_frame.grid(row=row_idx, column=0, sticky="new", pady=(0, 10))
            explanation_frame.columnconfigure(0, weight=1)

            explanation_text = scrolledtext.ScrolledText(explanation_frame, wrap=tk.WORD, height=10, font=("Segoe UI", 9))
            explanation_text.pack(fill="both", expand=True)
            explanation_text.insert("1.0", self.global_explanation)
            explanation_text.config(state=tk.DISABLED, background=self.cget('bg'))
            row_idx += 1
        
        view_switcher_frame = ttk.Frame(right_frame)
        view_switcher_frame.grid(row=row_idx, column=0, sticky="w", pady=(0, 5))
        ttk.Radiobutton(view_switcher_frame, text="Különbségek", variable=self.view_mode, value="diff", command=self._switch_view).pack(side=tk.LEFT)
        ttk.Radiobutton(view_switcher_frame, text="Side-by-Side", variable=self.view_mode, value="sbs", command=self._switch_view).pack(side=tk.LEFT, padx=10)
        row_idx += 1
        
        right_frame.rowconfigure(row_idx, weight=1)

        self.text_widget = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.text_widget.grid(row=row_idx, column=0, sticky="nsew")
        self.text_widget.tag_configure("addition", foreground="#008800")
        self.text_widget.tag_configure("deletion", foreground="#CC0000")
        self.text_widget.tag_configure("header", foreground="#0000FF", font=("Consolas", 11, "bold"))
        self.text_widget.tag_configure("info", foreground="grey", font=("Consolas", 10, "italic"))

        self.sbs_pane = ttk.PanedWindow(right_frame, orient=tk.HORIZONTAL)
        
        original_frame = ttk.LabelFrame(self.sbs_pane, text="Eredeti Tartalom")
        self.original_text = scrolledtext.ScrolledText(original_frame, wrap=tk.WORD, font=("Consolas", 10), state=tk.DISABLED)
        self.original_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.sbs_pane.add(original_frame, weight=1)
        self.original_text.tag_configure("sbs_deletion", background="#ffe0e0")

        modified_frame = ttk.LabelFrame(self.sbs_pane, text="Módosított Tartalom")
        self.modified_text = scrolledtext.ScrolledText(modified_frame, wrap=tk.WORD, font=("Consolas", 10), state=tk.DISABLED)
        self.modified_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self.sbs_pane.add(modified_frame, weight=1)
        self.modified_text.tag_configure("sbs_addition", background="#e0ffe0")

        self._scroll_sync_active = False
        self.original_text.config(yscrollcommand=self._sync_scroll_original)
        self.modified_text.config(yscrollcommand=self._sync_scroll_modified)

        button_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Kijelöltek elfogadása", command=self._accept_selected_changes).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Bezárás", command=self.destroy).pack(side=tk.RIGHT)

        self._populate_file_list()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        
        self._switch_view()
        if self.diff_results:
            self.file_listbox.selection_set(0)
            self._on_file_select()

    def _sync_scroll_original(self, *args):
        if not self._scroll_sync_active:
            self._scroll_sync_active = True
            self.modified_text.yview_moveto(args[0])
            self._scroll_sync_active = False

    def _sync_scroll_modified(self, *args):
        if not self._scroll_sync_active:
            self._scroll_sync_active = True
            self.original_text.yview_moveto(args[0])
            self._scroll_sync_active = False

    def _populate_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for i, result in enumerate(self.diff_results):
            status_map = {
                'modified': 'MÓDOSÍTOTT',
                'new': 'ÚJ',
                'accepted': 'ELFOGADVA',
                'error': 'HIBA',
                'new_from_modified': 'ÚJ (módosítottként jelölve)'
            }
            status_str = status_map.get(result.get('status', 'unknown'), 'ISMERETLEN').upper()
            display_text = f"[{status_str}] {result['path']}"
            self.file_listbox.insert(tk.END, display_text)
            self._update_listbox_item_color(i)

    def _update_listbox_item_color(self, index):
        status = self.diff_results[index].get('status')
        color_map = {
            'accepted': 'lightgreen',
            'error': '#ffdddd'
        }
        bg_color = color_map.get(status)
        if bg_color:
            self.file_listbox.itemconfig(index, {'bg': bg_color})
        else:
            self.file_listbox.itemconfig(index, {'bg': ''})

    def _switch_view(self):
        content_row = 1
        if self.global_explanation:
            content_row = 2
        
        if self.view_mode.get() == "sbs":
            self.text_widget.grid_remove()
            self.sbs_pane.grid(row=content_row, column=0, sticky="nsew")
        else:
            self.sbs_pane.grid_remove()
            self.text_widget.grid(row=content_row, column=0, sticky="nsew")
        
        self._on_file_select()

    def _on_file_select(self, event=None):
        selection_indices = self.file_listbox.curselection()
        if not selection_indices:
            self._display_views(None)
            return
        selected_index = selection_indices[0]
        self._display_views(self.diff_results[selected_index])

    def _display_views(self, result):
        self.text_widget.config(state=tk.NORMAL)
        self.original_text.config(state=tk.NORMAL)
        self.modified_text.config(state=tk.NORMAL)

        self.text_widget.delete("1.0", tk.END)
        self.original_text.delete("1.0", tk.END)
        self.modified_text.delete("1.0", tk.END)

        if not result:
            self.text_widget.insert(tk.END, "Válassz egy fájlt a listából a változások megtekintéséhez.", "info")
        else:
            status = result['status'].replace('_', ' ').upper()
            header_text = f"--- {status}: {result['path']} ---\n"
            self.text_widget.insert(tk.END, header_text, "header")

            if 'diff' not in result or not result['diff']:
                self.text_widget.insert(tk.END, "\n(Nincs megjeleníthető változás vagy csak a tartalom azonos)\n", "info")
            else:
                for line in result['diff']:
                    line_with_newline = line + '\n'
                    if line.startswith('+ '):
                        self.text_widget.insert(tk.END, line_with_newline, "addition")
                    elif line.startswith('- '):
                        self.text_widget.insert(tk.END, line_with_newline, "deletion")
                    elif not line.startswith('---') and not line.startswith('+++') and not line.startswith('@@'):
                        self.text_widget.insert(tk.END, "  " + line_with_newline)
            
            self._highlight_sbs_diffs(result)
        
        self.text_widget.config(state=tk.DISABLED)
        self.original_text.config(state=tk.DISABLED)
        self.modified_text.config(state=tk.DISABLED)

    def _highlight_sbs_diffs(self, result):
        if not result:
            return

        old_content = result.get('old_content', '')
        new_content = result.get('new_content', '')

        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()

        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for line in old_lines[i1:i2]:
                    self.original_text.insert(tk.END, line + '\n')
                for line in new_lines[j1:j2]:
                    self.modified_text.insert(tk.END, line + '\n')
            
            else:
                if i1 < i2:
                    for line in old_lines[i1:i2]:
                        self.original_text.insert(tk.END, line + '\n', "sbs_deletion")
                
                if j1 < j2:
                    for line in new_lines[j1:j2]:
                        self.modified_text.insert(tk.END, line + '\n', "sbs_addition")

                deleted_count = i2 - i1
                inserted_count = j2 - j1
                if deleted_count < inserted_count:
                    for _ in range(inserted_count - deleted_count):
                        self.original_text.insert(tk.END, '\n')
                elif inserted_count < deleted_count:
                    for _ in range(deleted_count - inserted_count):
                        self.modified_text.insert(tk.END, '\n')


    def _accept_selected_changes(self):
        selected_indices = self.file_listbox.curselection()
        if not selected_indices:
            messagebox.showwarning("Nincs kijelölés", "Jelölj ki egy vagy több fájlt az elfogadáshoz!", parent=self)
            return

        accepted_count = 0
        error_count = 0
        
        for index in selected_indices:
            file_data = self.diff_results[index]

            if file_data.get('status') == 'accepted':
                continue

            full_path = self.project_root / file_data['path']
            new_content = file_data['new_content']

            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(new_content, encoding='utf-8')
                
                file_data['status'] = 'accepted'
                accepted_count += 1
            except (IOError, PermissionError) as e:
                messagebox.showerror("Írási Hiba", f"Hiba a(z) '{full_path}' fájl írásakor:\n\n{e}", parent=self)
                file_data['status'] = 'error'
                error_count += 1
        
        self._populate_file_list()
        
        for index in selected_indices:
            self.file_listbox.selection_set(index)

        if accepted_count > 0 or error_count > 0:
            messagebox.showinfo("Művelet Befejezve", 
                f"Elfogadva: {accepted_count} fájl\nHibás: {error_count} fájl", parent=self)


class PromptManagerWindow(tk.Toplevel):
    def __init__(self, parent_app):
        super().__init__(parent_app.root)
        self.parent_app = parent_app

        self.title("Prompt Sablon Kezelő")
        self.geometry("800x700")
        self.transient(parent_app.root)
        self.grab_set()

        top_level_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        top_level_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        prompts_frame = ttk.Frame(top_level_pane, padding=5)
        top_level_pane.add(prompts_frame, weight=3)
        
        main_pane = ttk.PanedWindow(prompts_frame, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(left_frame, weight=1)
        ttk.Label(left_frame, text="Mentett Promptok", font="-weight bold").pack(pady=(0, 5))
        self.prompt_listbox = tk.Listbox(left_frame)
        self.prompt_listbox.pack(fill=tk.BOTH, expand=True)
        self.prompt_listbox.bind("<<ListboxSelect>>", self.on_listbox_select)

        right_frame = ttk.Frame(main_pane, padding=5)
        main_pane.add(right_frame, weight=3)
        ttk.Label(right_frame, text="Cím:", anchor="w").pack(fill=tk.X)
        self.title_entry = ttk.Entry(right_frame)
        self.title_entry.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(right_frame, text="Tartalom:", anchor="w").pack(fill=tk.X)
        self.content_text = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, height=10)
        self.content_text.pack(fill=tk.BOTH, expand=True)

        prefs_frame = ttk.LabelFrame(top_level_pane, text="Általános beállítások", padding=10)
        top_level_pane.add(prefs_frame, weight=1)
        prefs_frame.columnconfigure(0, weight=1)
        prefs_frame.rowconfigure(1, weight=1)

        ttk.Label(prefs_frame, text="Globális prompt előtag (mindig bekerül a promptok és a fájlok közé):").grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.preferences_text = scrolledtext.ScrolledText(prefs_frame, wrap=tk.WORD, height=4)
        self.preferences_text.grid(row=1, column=0, sticky="nsew")

        button_frame = ttk.Frame(self, padding=(10, 5, 10, 10))
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Új Prompt", command=self.new_prompt).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Törlés", command=self.delete_prompt).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Bezárás", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(button_frame, text="Mentés", command=self.save_all).pack(side=tk.RIGHT, padx=(0, 5))
        
        self.populate_listbox()
        self.populate_preferences()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def populate_preferences(self):
        prefix = self.parent_app.preferences.get("global_prefix", "")
        self.preferences_text.delete("1.0", tk.END)
        self.preferences_text.insert("1.0", prefix)

    def populate_listbox(self):
        self.prompt_listbox.delete(0, tk.END)
        for prompt in sorted(self.parent_app.prompts, key=lambda p: p['title']):
            self.prompt_listbox.insert(tk.END, prompt['title'])

    def on_listbox_select(self, event=None):
        selection_indices = self.prompt_listbox.curselection()
        if not selection_indices:
            return
        
        selected_title = self.prompt_listbox.get(selection_indices[0])
        for prompt in self.parent_app.prompts:
            if prompt['title'] == selected_title:
                self.title_entry.delete(0, tk.END)
                self.title_entry.insert(0, prompt['title'])
                self.content_text.delete("1.0", tk.END)
                self.content_text.insert("1.0", prompt['content'])
                return

    def new_prompt(self):
        self.prompt_listbox.selection_clear(0, tk.END)
        self.title_entry.delete(0, tk.END)
        self.content_text.delete("1.0", tk.END)
        self.title_entry.focus()

    def save_all(self):
        title = self.title_entry.get().strip()
        if title:
            content = self.content_text.get("1.0", tk.END).strip()
            prompt_found = False
            for i, prompt in enumerate(self.parent_app.prompts):
                if prompt['title'] == title:
                    self.parent_app.prompts[i] = {'title': title, 'content': content}
                    prompt_found = True
                    break
            if not prompt_found:
                self.parent_app.prompts.append({'title': title, 'content': content})

        global_prefix = self.preferences_text.get("1.0", tk.END).strip()
        self.parent_app.preferences['global_prefix'] = global_prefix

        self.parent_app.save_prompts_and_prefs()
        self.parent_app.update_prompt_combobox()
        self.populate_listbox()
        
        messagebox.showinfo("Siker", "A promptok és beállítások elmentve.", parent=self)

    def delete_prompt(self):
        selection_indices = self.prompt_listbox.curselection()
        if not selection_indices:
            messagebox.showwarning("Figyelmeztetés", "Nincs kiválasztva prompt a törléshez.", parent=self)
            return
        
        selected_title = self.prompt_listbox.get(selection_indices[0])
        
        if messagebox.askyesno("Törlés megerősítése", f"Biztosan törli a '{selected_title}' promptot?", parent=self):
            self.parent_app.prompts = [p for p in self.parent_app.prompts if p['title'] != selected_title]
            self.parent_app.save_prompts_and_prefs()
            self.parent_app.update_prompt_combobox()
            self.populate_listbox()
            self.new_prompt() 
            messagebox.showinfo("Siker", f"'{selected_title}' prompt törölve.", parent=self)


class LLMContextCollectorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LLM Kontextus Gyűjtő v9.0 (Szerkeszthető Prompt)")
        self.root.geometry("1250x850")

        self.selected_folder = tk.StringVar()
        self.char_count = tk.IntVar(value=0)
        self.token_count = tk.IntVar(value=0)
        self.status_text = tk.StringVar(value="Készen áll.")
        self.search_term = tk.StringVar()
        self.selected_prompt = tk.StringVar()
        self.ref_search_depth = tk.IntVar(value=1)
        self.search_in_content_var = tk.BooleanVar(value=False)
        self.copy_prompt_var = tk.BooleanVar(value=True)
        self.copy_global_prompt_var = tk.BooleanVar(value=True)

        self.current_gitignore_matcher = None
        self.scan_queue = queue.Queue()
        self.update_queue = queue.Queue()
        self.all_tree_items_data = []
        self.all_tree_items_map = {}
        self.file_path_to_iid_map = {}
        self.files_to_preserve_on_reload = set()
        
        self.history_file_path = self.get_config_file_path(HISTORY_FILENAME)
        self.history_entries = self.load_json_data(self.history_file_path, is_history=True)
        
        self.prompt_file_path = self.get_config_file_path(PROMPT_FILENAME)
        self.prompts = []
        self.preferences = {}
        self.load_prompts_and_prefs()

        self.listbox_history = [()]
        self.listbox_history_index = 0
        self._preview_update_job = None
        
        main_frame = ttk.Frame(root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 5))
        folder_button = ttk.Button(top_frame, text="Projekt Mappa...", command=self.select_folder)
        folder_button.pack(side=tk.LEFT, padx=(0, 10))
        folder_label = ttk.Label(top_frame, textvariable=self.selected_folder, relief="sunken", padding=5)
        folder_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        history_frame = ttk.Frame(main_frame)
        history_frame.pack(fill=tk.X, pady=(0, 5))
        history_label = ttk.Label(history_frame, text="Előzmények:")
        history_label.pack(side=tk.LEFT, padx=(0, 5))
        self.history_combobox = ttk.Combobox(history_frame, state="readonly", width=80)
        self.history_combobox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.update_history_combobox()
        self.history_combobox.bind("<<ComboboxSelected>>", self.load_selected_history_entry)
        
        search_frame = ttk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 5))
        search_label = ttk.Label(search_frame, text="Keresés fában:")
        search_label.pack(side=tk.LEFT, padx=(0, 5))
        search_entry = ttk.Entry(search_frame, textvariable=self.search_term, width=40)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        
        search_in_content_check = ttk.Checkbutton(search_frame, text="Referenciák keresése", variable=self.search_in_content_var)
        search_in_content_check.pack(side=tk.LEFT, padx=(0, 5))
        
        search_button = ttk.Button(search_frame, text="Keresés", command=self.filter_treeview)
        search_button.pack(side=tk.LEFT, padx=(0,5))
        clear_search_button = ttk.Button(search_frame, text="Törlés", command=self.clear_search)
        clear_search_button.pack(side=tk.LEFT)
        search_entry.bind("<Return>", lambda event: self.filter_treeview())

        center_pane = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        center_pane.pack(fill=tk.BOTH, expand=True)
        
        left_pane = ttk.Frame(center_pane, padding=(0,0,5,0))
        center_pane.add(left_pane, weight=2)
        left_pane.rowconfigure(0, weight=1)
        left_pane.columnconfigure(0, weight=1)
        tree_frame = ttk.Frame(left_pane)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        
        self.tree = ttk.Treeview(tree_frame, selectmode='extended')
        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        xsb = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)
        ysb.grid(row=0, column=1, sticky='ns')
        xsb.grid(row=1, column=0, sticky='ew')
        self.tree['columns'] = ('fullpath', 'type')
        self.tree.column('#0', width=300, minwidth=200, anchor='w')
        self.tree.column('fullpath', width=0, stretch=tk.NO)
        self.tree.column('type', width=0, stretch=tk.NO)
        self.tree.heading('#0', text='Fájlok és Mappák', anchor='w')
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_selection_change)

        self.tree_context_menu = tk.Menu(self.root, tearoff=0)
        self.tree_context_menu.add_command(label="Hozzáadás a kontextushoz", command=self.add_selected_to_list)
        self.tree_context_menu.add_separator()
        self.tree_context_menu.add_command(label="Kijelöltek kizárása", command=self.exclude_selected_from_tree)
        self.tree.bind("<Button-3>", self.show_tree_context_menu)
        self.tree.bind("<Button-2>", self.show_tree_context_menu)

        middle_pane = ttk.Frame(center_pane, padding=(5,0,5,0))
        center_pane.add(middle_pane, weight=1)
        button_panel = ttk.Frame(middle_pane)
        button_panel.pack(anchor=tk.N)
        
        add_button = ttk.Button(button_panel, text="Hozzáadás >>", command=self.add_selected_to_list)
        add_button.pack(pady=5, fill=tk.X)
        
        exclude_button = ttk.Button(button_panel, text="Kizárás", command=self.exclude_selected_from_tree)
        exclude_button.pack(pady=5, fill=tk.X)

        remove_button = ttk.Button(button_panel, text="<< Eltávolítás", command=self.remove_selected_from_list)
        remove_button.pack(pady=5, fill=tk.X)
        
        ref_search_container = ttk.Frame(button_panel)
        ref_search_container.pack(pady=15, fill=tk.X)

        ref_search_label = ttk.Label(ref_search_container, text="Referencia mélység:")
        ref_search_label.pack(side=tk.LEFT, padx=(0, 5))

        self.ref_search_depth_spinbox = ttk.Spinbox(
            ref_search_container, from_=0, to=3, 
            textvariable=self.ref_search_depth, width=3
        )
        self.ref_search_depth_spinbox.pack(side=tk.LEFT)
        
        filter_frame = ttk.LabelFrame(button_panel, text="Szűrők", padding=5)
        filter_frame.pack(pady=5, fill=tk.X, expand=True)
        filter_frame.columnconfigure(0, weight=1)

        self.extension_vars = {ext: tk.BooleanVar(value=True) for ext in DEFAULT_EXTENSIONS}
        ttk.Label(filter_frame, text="Aktív fájltípusok:").grid(row=0, column=0, columnspan=2, sticky="w", padx=2, pady=(0, 2))
        
        ext_container = ttk.Frame(filter_frame)
        ext_container.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(0, 5))
        ext_container.rowconfigure(0, weight=1)
        ext_container.columnconfigure(0, weight=1)
        ext_canvas = tk.Canvas(ext_container, borderwidth=0, highlightthickness=0, height=130)
        ext_scrollbar = ttk.Scrollbar(ext_container, orient="vertical", command=ext_canvas.yview)
        self.ext_checklist_frame = ttk.Frame(ext_canvas)
        ext_canvas.configure(yscrollcommand=ext_scrollbar.set)
        ext_scrollbar.pack(side="right", fill="y")
        ext_canvas.pack(side="left", fill="both", expand=True)
        ext_canvas_window = ext_canvas.create_window((0, 0), window=self.ext_checklist_frame, anchor="nw")

        def on_ext_frame_configure(event):
            ext_canvas.configure(scrollregion=ext_canvas.bbox("all"))
        self.ext_checklist_frame.bind("<Configure>", on_ext_frame_configure)
        
        def on_canvas_configure(event):
            ext_canvas.itemconfig(ext_canvas_window, width=event.width)
        ext_canvas.bind("<Configure>", on_canvas_configure, add="+")

        add_ext_frame = ttk.Frame(filter_frame)
        add_ext_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5,0))
        add_ext_frame.columnconfigure(0, weight=1)
        
        self.new_ext_entry = ttk.Entry(add_ext_frame, font=("Segoe UI", 8))
        self.new_ext_entry.grid(row=0, column=0, sticky="ew", padx=(0,5))
        add_ext_button = ttk.Button(add_ext_frame, text="+", command=self._add_extension, width=3)
        add_ext_button.grid(row=0, column=1)
        
        self._rebuild_extension_checklist()

        ttk.Label(filter_frame, text="Kizárások:").grid(row=3, column=0, columnspan=2, sticky="w", padx=2, pady=(2, 2))
        self.ignore_text = tk.Text(filter_frame, height=12, wrap="none", width=20)
        self.ignore_text.grid(row=4, column=0, columnspan=2, sticky="ew", padx=2, pady=(0, 0))
        self.ignore_text.insert("1.0", "\n".join(DEFAULT_IGNORE_PATTERNS))
        
        ignore_xsb = ttk.Scrollbar(filter_frame, orient='horizontal', command=self.ignore_text.xview)
        ignore_xsb.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(0, 5))
        self.ignore_text.configure(xscrollcommand=ignore_xsb.set)

        apply_filters_button = ttk.Button(filter_frame, text="Alkalmaz és Újratölt", command=self.apply_filters)
        apply_filters_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(5,0))

        right_pane = ttk.Frame(center_pane, padding=(5,0,0,0))
        center_pane.add(right_pane, weight=3)
        right_pane.rowconfigure(0, weight=1)
        right_pane.columnconfigure(0, weight=1)

        right_vertical_pane = ttk.PanedWindow(right_pane, orient=tk.VERTICAL)
        right_vertical_pane.grid(row=0, column=0, sticky="nsew")

        right_top_controls = ttk.Frame(right_vertical_pane)
        right_vertical_pane.add(right_top_controls, weight=0)
        right_top_controls.columnconfigure(0, weight=1)
        
        prompt_frame = ttk.LabelFrame(right_top_controls, text="Prompt Sablon", padding=5)
        prompt_frame.grid(row=0, column=0, sticky="new", pady=(0,5))
        prompt_frame.columnconfigure(0, weight=1)
        self.prompt_combobox = ttk.Combobox(prompt_frame, textvariable=self.selected_prompt, state="readonly")
        self.prompt_combobox.grid(row=0, column=0, sticky="ew")
        copy_prompt_button = ttk.Button(prompt_frame, text="📋", command=self.copy_prompt_only, width=3)
        copy_prompt_button.grid(row=0, column=1, sticky="e", padx=5)
        prompt_edit_button = ttk.Button(prompt_frame, text="Szerkesztés...", command=self.open_prompt_manager)
        prompt_edit_button.grid(row=0, column=2, sticky="e")
        self.update_prompt_combobox()
        self.prompt_combobox.bind("<<ComboboxSelected>>", self.on_prompt_template_selected)

        prompt_editor_frame = ttk.LabelFrame(right_vertical_pane, text="Prompt Szerkesztő", padding=5)
        right_vertical_pane.add(prompt_editor_frame, weight=2)
        prompt_editor_frame.rowconfigure(0, weight=1)
        prompt_editor_frame.columnconfigure(0, weight=1)
        self.editable_prompt_text = scrolledtext.ScrolledText(prompt_editor_frame, wrap=tk.WORD, height=8, font=("Segoe UI", 9))
        self.editable_prompt_text.grid(row=0, column=0, sticky="nsew")

        selected_files_container = ttk.Frame(right_vertical_pane, padding=(0,5,0,5))
        right_vertical_pane.add(selected_files_container, weight=3)
        selected_files_container.rowconfigure(0, weight=1)
        selected_files_container.columnconfigure(0, weight=1)

        selected_files_frame = ttk.LabelFrame(selected_files_container, text="Kiválasztott Fájlok (Kontextushoz)", padding="5")
        selected_files_frame.grid(row=0, column=0, sticky="nsew")
        selected_files_frame.rowconfigure(0, weight=1)
        selected_files_frame.columnconfigure(0, weight=1)
        self.selected_listbox = tk.Listbox(selected_files_frame, selectmode=tk.EXTENDED)
        self.selected_listbox.grid(row=0, column=0, sticky="nsew")
        list_ysb = ttk.Scrollbar(selected_files_frame, orient='vertical', command=self.selected_listbox.yview)
        list_ysb.grid(row=0, column=1, sticky='ns')
        self.selected_listbox.configure(yscrollcommand=list_ysb.set)
        self.selected_listbox.bind('<<ListboxSelect>>', self.on_listbox_selection_change)
        self.selected_listbox.bind("<Delete>", lambda event: self.remove_selected_from_list())
        
        self.listbox_context_menu = tk.Menu(self.root, tearoff=0)
        self.listbox_context_menu.add_command(label="Eltávolítás", command=self.remove_selected_from_list)
        self.selected_listbox.bind("<Button-3>", self.show_listbox_context_menu)
        self.selected_listbox.bind("<Button-2>", self.show_listbox_context_menu)

        list_actions_frame = ttk.Frame(selected_files_container)
        list_actions_frame.grid(row=1, column=0, sticky="ew", pady=(5,0))
        list_actions_frame.columnconfigure(2, weight=1)
        self.undo_button = ttk.Button(list_actions_frame, text="⮌ Vissza", command=self.undo_list_change, state=tk.DISABLED)
        self.undo_button.grid(row=0, column=0, padx=(0, 2))
        self.redo_button = ttk.Button(list_actions_frame, text="Előre ⮍", command=self.redo_list_change, state=tk.DISABLED)
        self.redo_button.grid(row=0, column=1, padx=(0, 10))
        clear_list_button = ttk.Button(list_actions_frame, text="Kiválasztott lista ürítése", command=self.clear_selection_list)
        clear_list_button.grid(row=0, column=2, sticky="ew")

        preview_frame = ttk.LabelFrame(right_vertical_pane, text="Fájl Előnézet", padding="5")
        right_vertical_pane.add(preview_frame, weight=2)
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview_text = scrolledtext.ScrolledText(preview_frame, wrap=tk.WORD, state=tk.DISABLED, height=10, font=("Consolas", 9))
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        count_frame = ttk.Frame(bottom_frame)
        count_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        char_label = ttk.Label(count_frame, text="Karakterek:")
        char_label.pack(side=tk.LEFT)
        char_value = ttk.Label(count_frame, textvariable=self.char_count, width=10, anchor='e')
        char_value.pack(side=tk.LEFT, padx=(0, 10))
        token_label = ttk.Label(count_frame, text="Tokenek (becsült):")
        token_label.pack(side=tk.LEFT)
        token_value = ttk.Label(count_frame, textvariable=self.token_count, width=10, anchor='e')
        token_value.pack(side=tk.LEFT)
        button_frame = ttk.Frame(bottom_frame)
        button_frame.pack(side=tk.RIGHT)

        changes_button = ttk.Button(button_frame, text="Változások Vágólapról", command=self.process_changes_from_clipboard)
        changes_button.pack(side=tk.LEFT, padx=(0, 5))

        prompt_check = ttk.Checkbutton(button_frame, text="Prompt", variable=self.copy_prompt_var)
        prompt_check.pack(side=tk.LEFT, padx=(0, 2))
        global_prompt_check = ttk.Checkbutton(button_frame, text="Globális", variable=self.copy_global_prompt_var)
        global_prompt_check.pack(side=tk.LEFT, padx=(0, 5))

        copy_button = ttk.Button(button_frame, text="Másolás vágólapra", command=self.copy_to_clipboard)
        copy_button.pack(side=tk.LEFT, padx=(0, 5))
        save_button = ttk.Button(button_frame, text="Mentés fájlba...", command=self.save_to_file)
        save_button.pack(side=tk.LEFT)
        status_bar = ttk.Label(root, textvariable=self.status_text, relief=tk.SUNKEN, anchor=tk.W, padding=5)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.root.after(100, self.process_update_queue)
        self.root.after(200, self.load_latest_history)

    def _rebuild_extension_checklist(self):
        for widget in self.ext_checklist_frame.winfo_children():
            widget.destroy()

        self.ext_checklist_frame.columnconfigure(0, weight=1)
        self.ext_checklist_frame.columnconfigure(1, weight=1)
        
        sorted_exts = sorted(self.extension_vars.keys())
        
        for i, ext in enumerate(sorted_exts):
            var = self.extension_vars[ext]
            cb = ttk.Checkbutton(self.ext_checklist_frame, text=ext, variable=var)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=2, pady=1)

    def _add_extension(self):
        new_ext = self.new_ext_entry.get().strip().lower()
        if not new_ext:
            return
        if not new_ext.startswith('.'):
            new_ext = '.' + new_ext
        
        if new_ext not in self.extension_vars:
            self.extension_vars[new_ext] = tk.BooleanVar(value=True)
            self._rebuild_extension_checklist()
            
        self.new_ext_entry.delete(0, tk.END)

    def on_prompt_template_selected(self, event=None):
        selected_title = self.selected_prompt.get()
        self.editable_prompt_text.delete("1.0", tk.END)
        
        if not selected_title or selected_title == "(Nincs)":
            return

        for prompt in self.prompts:
            if prompt['title'] == selected_title:
                self.editable_prompt_text.insert("1.0", prompt.get('content', ''))
                break

    def process_changes_from_clipboard(self):
        try:
            clipboard_text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Hiba", "A vágólap üres vagy nem érhető el.", parent=self.root)
            return

        project_root = self.selected_folder.get()
        if not project_root:
            messagebox.showerror("Hiba", "Nincs projekt mappa kiválasztva. A módosítások nem ellenőrizhetők.", parent=self.root)
            return

        global_explanation, parsed_files = self._parse_llm_response(clipboard_text)

        if not parsed_files:
            messagebox.showinfo("Információ", "Nem sikerült fájl-változásokat találni a vágólap tartalmában.", parent=self.root)
            return
            
        self.status_text.set(f"Fájlok elemzése ({len(parsed_files)} db)...")
        self.root.update_idletasks()

        diff_results = []
        for file_data in parsed_files:
            rel_path = file_data['path']
            full_path = pathlib.Path(project_root) / rel_path
            old_content = ""
            status = file_data['status']
            
            new_content_clean = file_data['new_content'].strip().replace('\r\n', '\n')
            new_lines = new_content_clean.splitlines()
            diff_list = []

            if status == 'modified':
                if full_path.is_file():
                    try:
                        old_content = full_path.read_text(encoding='utf-8').replace('\r\n', '\n')
                    except Exception:
                        try: old_content = full_path.read_text(encoding='latin-1').replace('\r\n', '\n')
                        except Exception as e: print(f"Hiba a fájl olvasásakor ({full_path}): {e}")
                else:
                    status = 'new_from_modified'
            
            if status.startswith('new'):
                diff_list = ['+ ' + line for line in new_lines]
            else:
                old_lines = old_content.splitlines()
                diff_generator = difflib.unified_diff(
                    old_lines, new_lines, fromfile=f'a/{rel_path}', tofile=f'b/{rel_path}', lineterm='')
                diff_list = list(diff_generator)
            
            diff_results.append({
                'path': rel_path, 'diff': diff_list, 'status': status,
                'new_content': new_content_clean, 'old_content': old_content
            })
        
        self.status_text.set("Kész. Diff ablak megnyitása...")
        self.show_diff_window(global_explanation, diff_results)

    def _parse_llm_response(self, text: str) -> tuple[str, list]:
        first_block_pattern = re.compile(r'^(Új Fájl|Fájl):', re.MULTILINE | re.IGNORECASE)
        first_match = first_block_pattern.search(text)
        
        global_explanation = ""
        content_to_parse = text

        if first_match:
            global_explanation = text[:first_match.start()].strip()
            content_to_parse = text[first_match.start():]

        file_pattern = re.compile(
            r'^(Új Fájl|Fájl):\s*([^\n]+?)\s*'
            r'\`\`\`[a-zA-Z]*\n'
            r'(.*?)'
            r'\n?\`\`\`',
            re.DOTALL | re.MULTILINE | re.IGNORECASE
        )

        matches = file_pattern.findall(content_to_parse)
        
        extracted_data = []
        for status_text, path, content in matches:
            normalized_path = path.strip().replace('\\', '/')
            status = 'new' if 'új' in status_text.lower() else 'modified'
            
            extracted_data.append({
                'path': normalized_path,
                'new_content': content.strip(),
                'status': status
            })
            
        return global_explanation, extracted_data


    def show_diff_window(self, global_explanation, diff_results):
        project_root = self.selected_folder.get()
        if project_root:
            DiffWindow(self.root, global_explanation, diff_results, project_root)

    def filter_treeview(self, event=None):
        term = self.search_term.get().lower().strip()
        search_in_content = self.search_in_content_var.get()

        if not term:
            self.clear_search()
            return

        if not self.all_tree_items_data:
            return

        self.status_text.set(f"Keresés: '{term}'..."); self.root.update_idletasks()

        matching_file_ids_by_name = set()
        matching_folder_ids_by_name = set()
        for _, item_type, display_name, full_path in self.all_tree_items_data:
            if term in display_name.lower():
                if item_type == 'file':
                    matching_file_ids_by_name.add(full_path)
                elif item_type == 'folder':
                    matching_folder_ids_by_name.add(full_path)

        matching_file_ids_by_content = set()
        if search_in_content:
            self.status_text.set(f"Keresés névben és tartalomban: '{term}'..."); self.root.update_idletasks()
            all_files_to_scan = [item for item in self.all_tree_items_data if item[1] == 'file']
            for _, _, _, file_path in all_files_to_scan:
                try:
                    content = self._read_file_content_safely(file_path)
                    if term in content.lower():
                        matching_file_ids_by_content.add(file_path)
                except Exception as e:
                    print(f"Hiba a tartalomkeresés közben: {file_path} - {e}")

        final_matching_file_ids = matching_file_ids_by_name.union(matching_file_ids_by_content)
        ref_only_ids = matching_file_ids_by_content - matching_file_ids_by_name

        all_ids_to_display = set()
        parents_to_add = set()

        for item_id in final_matching_file_ids:
            all_ids_to_display.add(item_id)
            parent_id = self.all_tree_items_map.get(item_id, (None, None, None))[0]
            while parent_id:
                parents_to_add.add(parent_id)
                parent_id = self.all_tree_items_map.get(parent_id, (None, None, None))[0]
        all_ids_to_display.update(parents_to_add)

        for folder_id in matching_folder_ids_by_name:
            all_ids_to_display.add(folder_id)
            all_ids_to_display.update(self._get_all_descendants(folder_id))

        items_to_display_data = []
        for item in self.all_tree_items_data:
            parent, type, name, path = item
            if path in all_ids_to_display:
                if path in ref_only_ids:
                    display_name = f"[REF] {name}"
                    items_to_display_data.append((parent, type, display_name, path))
                else:
                    items_to_display_data.append(item)
        
        self._populate_tree_from_data(items_to_display_data)

        for item_id in parents_to_add:
            if self.tree.exists(item_id): self.tree.item(item_id, open=True)
        for folder_id in matching_folder_ids_by_name:
            if self.tree.exists(folder_id): self.tree.item(folder_id, open=True)

        self.status_text.set(f"{len(final_matching_file_ids) + len(matching_folder_ids_by_name)} elem található.")

    def add_selected_to_list(self):
        selected_ids = self.tree.selection()
        if not selected_ids:
            self.status_text.set("Nincs elem kiválasztva a fában.")
            return
        
        root_folder = self.selected_folder.get()
        if not root_folder:
            return
        base_path = pathlib.Path(root_folder)
        
        current_list_items = set(self.selected_listbox.get(0, tk.END))
        files_to_add_rel = set()

        def collect_visible_files_from_tree(folder_id):
            for child_id in self.tree.get_children(folder_id):
                values = self.tree.item(child_id, 'values')
                if not values: continue
                
                child_path_str, child_type = values
                if child_type == 'file':
                    try:
                        files_to_add_rel.add(pathlib.Path(child_path_str).relative_to(base_path).as_posix())
                    except ValueError: pass
                elif child_type == 'folder':
                    collect_visible_files_from_tree(child_id)

        for item_id in selected_ids:
            values = self.tree.item(item_id, 'values')
            if not values: continue

            item_path_str, item_type = values
            if item_type == 'file':
                try:
                    files_to_add_rel.add(pathlib.Path(item_path_str).relative_to(base_path).as_posix())
                except ValueError: pass
            elif item_type == 'folder':
                collect_visible_files_from_tree(item_id)
        
        newly_added = files_to_add_rel - current_list_items
        
        if newly_added:
            all_items = sorted(list(current_list_items.union(newly_added)))
            self.selected_listbox.delete(0, tk.END)
            for rel_path in all_items:
                self.selected_listbox.insert(tk.END, rel_path)
            self.status_text.set(f"{len(newly_added)} fájl hozzáadva.")
            self.update_listbox_based_counts()
            self._save_listbox_state()
        else:
            self.status_text.set("Nincs új fájl hozzáadva (már a listán voltak).")

        if self.ref_search_depth.get() > 0:
            self.find_related_references()

    def clear_search(self):
        self.search_term.set("")
        self.search_in_content_var.set(False)
        if self.all_tree_items_data:
            self._populate_tree_from_data(self.all_tree_items_data)
        self.status_text.set("Fa nézet visszaállítva.")

    def _read_file_content_safely(self, file_path):
        content = ""
        encodings = ['utf-8', 'cp1250', 'cp1252', 'latin1']
        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                return content
            except (UnicodeDecodeError, IOError):
                continue
        return ""

    def load_latest_history(self):
        if not self.history_entries:
            self.status_text.set("Készen áll. Nincs betölthető előzmény.")
            return
        
        latest_entry = self.history_entries[0]
        self.status_text.set("Legutóbbi előzmény betöltése...")
        if not self._load_history_entry_data(latest_entry):
            self.status_text.set("Hiba a legutóbbi előzmény betöltésekor. Ellenőrizd a mappát.")

    def _load_history_entry_data(self, entry_to_load):
        try:
            folder = entry_to_load.get("root_folder")
            if not folder or not os.path.isdir(folder):
                return False

            self.selected_folder.set(folder)
            
            history_ext_str = entry_to_load.get("extensions_filter", "")
            history_exts = {ext.strip() for ext in history_ext_str.split(',') if ext.strip()}
            
            for ext in history_exts:
                if ext not in self.extension_vars:
                    self.extension_vars[ext] = tk.BooleanVar(value=False)

            for ext, var in self.extension_vars.items():
                var.set(ext in history_exts)
            
            self._rebuild_extension_checklist()

            self.ignore_text.delete("1.0", tk.END)
            self.ignore_text.insert("1.0", entry_to_load.get("ignore_filter", ""))
            
            self.editable_prompt_text.delete("1.0", tk.END)
            prompt_text_from_history = entry_to_load.get("prompt_text")
            
            if prompt_text_from_history is not None:
                self.editable_prompt_text.insert("1.0", prompt_text_from_history)
                template_title = entry_to_load.get("selected_template_title", "(Nincs)")
                if template_title in self.prompt_combobox['values']:
                    self.selected_prompt.set(template_title)
                else:
                    self.selected_prompt.set("(Nincs)")
            else: 
                prompt_to_load_title = entry_to_load.get("prompt_template", "(Nincs)")
                if prompt_to_load_title in self.prompt_combobox['values']:
                    self.selected_prompt.set(prompt_to_load_title)
                    self.on_prompt_template_selected() 
                else:
                    self.selected_prompt.set("(Nincs)")
            
            self.apply_filters()
            self.root.after(1000, lambda: self.load_history_files(entry_to_load, is_startup=True))
            return True
        except Exception as e:
            print(f"Hiba az előzmény betöltésekor: {e}")
            return False

    def load_selected_history_entry(self, event=None):
        selected_index = self.history_combobox.current()
        if selected_index < 0: return
        
        entry_to_load = self.history_entries[selected_index]
        if not self._load_history_entry_data(entry_to_load):
            messagebox.showerror("Betöltési Hiba", 
                f"Hiba az előzmény betöltésekor. Ellenőrizd, hogy a mappa létezik-e:\n{entry_to_load.get('root_folder')}")

    def load_history_files(self, entry_to_load, is_startup=False):
        self.selected_listbox.delete(0, tk.END)
        loaded_files = entry_to_load.get("selected_files", [])
        for file_path in loaded_files:
            self.selected_listbox.insert(tk.END, file_path)
        self.update_listbox_based_counts()
        self._save_listbox_state()
        
        if not is_startup:
            self.status_text.set(f"Előzmény betöltve: {os.path.basename(entry_to_load.get('root_folder'))}")
        else:
            self.status_text.set(f"Legutóbbi előzmény betöltve. Készen áll.")
    
    def show_tree_context_menu(self, event):
        if self.tree.selection():
            self.tree_context_menu.post(event.x_root, event.y_root)

    def show_listbox_context_menu(self, event):
        if self.selected_listbox.curselection():
            self.listbox_context_menu.post(event.x_root, event.y_root)

    def open_prompt_manager(self):
        PromptManagerWindow(self)

    def update_prompt_combobox(self):
        titles = ["(Nincs)"] + sorted([p['title'] for p in self.prompts])
        current_selection = self.selected_prompt.get()
        self.prompt_combobox['values'] = titles
        if current_selection in titles:
            self.selected_prompt.set(current_selection)
        else:
            self.selected_prompt.set("(Nincs)")

    def save_prompts_and_prefs(self):
        data_to_save = {
            "preferences": self.preferences,
            "prompts": self.prompts
        }
        try:
            with open(self.prompt_file_path, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Hiba", f"Nem sikerült a promptokat és beállításokat menteni:\n{e}")

    def load_prompts_and_prefs(self):
        if not self.prompt_file_path.exists():
            self.prompts = []
            self.preferences = {}
            return
        
        try:
            with open(self.prompt_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                self.prompts = data
                self.preferences = {}
            elif isinstance(data, dict):
                self.prompts = data.get("prompts", [])
                self.preferences = data.get("preferences", {})
            else:
                self.prompts = []
                self.preferences = {}

        except (json.JSONDecodeError, Exception) as e:
            print(f"Hiba a(z) {self.prompt_file_path.name} betöltésekor: {e}")
            self.prompts = []
            self.preferences = {}

    def copy_prompt_only(self):
        prompt_content = self.editable_prompt_text.get("1.0", tk.END).strip()
        if not prompt_content:
            self.status_text.set("Nincs prompt a szerkesztőben a másoláshoz.")
            return

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(prompt_content)
            self.status_text.set("A szerkesztőben lévő prompt vágólapra másolva.")
        except tk.TclError:
            messagebox.showerror("Hiba", "Nem sikerült a vágólapra másolni.")

    def get_config_file_path(self, filename):
        home = pathlib.Path.home()
        return home / filename

    def load_json_data(self, file_path, is_history=False):
        if not file_path.exists():
            return []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if is_history:
                return data if isinstance(data, list) else []
            return data
        except (json.JSONDecodeError, Exception) as e:
            print(f"Hiba a(z) {file_path.name} betöltésekor: {e}")
            return [] if is_history else {}
    
    def _save_listbox_state(self):
        current_state = self.selected_listbox.get(0, tk.END)
        if self.listbox_history_index < len(self.listbox_history) - 1:
            self.listbox_history = self.listbox_history[:self.listbox_history_index + 1]
        if not self.listbox_history or self.listbox_history[-1] != current_state:
            self.listbox_history.append(current_state)
            self.listbox_history_index = len(self.listbox_history) - 1
        self._update_undo_redo_buttons_state()

    def _restore_listbox_state(self, state):
        self.selected_listbox.delete(0, tk.END)
        for item in state:
            self.selected_listbox.insert(tk.END, item)
        self.update_listbox_based_counts()

    def undo_list_change(self):
        if self.listbox_history_index > 0:
            self.listbox_history_index -= 1
            state_to_restore = self.listbox_history[self.listbox_history_index]
            self._restore_listbox_state(state_to_restore)
            self.status_text.set("Visszavonva.")
        self._update_undo_redo_buttons_state()

    def redo_list_change(self):
        if self.listbox_history_index < len(self.listbox_history) - 1:
            self.listbox_history_index += 1
            state_to_restore = self.listbox_history[self.listbox_history_index]
            self._restore_listbox_state(state_to_restore)
            self.status_text.set("Ismételve.")
        self._update_undo_redo_buttons_state()

    def _update_undo_redo_buttons_state(self):
        can_undo = self.listbox_history_index > 0
        can_redo = self.listbox_history_index < len(self.listbox_history) - 1
        self.undo_button.config(state=tk.NORMAL if can_undo else tk.DISABLED)
        self.redo_button.config(state=tk.NORMAL if can_redo else tk.DISABLED)
    
    def save_history(self):
        folder = self.selected_folder.get()
        if not folder:
            return
        if not self.get_selected_content().strip():
            return

        prompt_text = self.editable_prompt_text.get("1.0", tk.END).strip()

        current_state = {
            "timestamp": datetime.now().isoformat(),
            "root_folder": folder,
            "selected_files": list(self.selected_listbox.get(0, tk.END)),
            "extensions_filter": ", ".join(self.get_current_extensions()),
            "ignore_filter": self.ignore_text.get("1.0", tk.END).strip(),
            "prompt_text": prompt_text,
            "selected_template_title": self.selected_prompt.get()
        }
        
        history = self.load_json_data(self.history_file_path, is_history=True)
        history.insert(0, current_state)
        history = history[:HISTORY_LIMIT]
        
        try:
            with open(self.history_file_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
            self.history_entries = history
            self.update_history_combobox()
        except Exception as e:
            messagebox.showerror("Mentési Hiba", f"Nem sikerült az előzményeket menteni:\n{e}")

    def update_history_combobox(self):
        display_values = []
        for entry in self.history_entries:
            try:
                ts = datetime.fromisoformat(entry.get("timestamp", "")).strftime('%y-%m-%d %H:%M')
                folder_name = os.path.basename(entry.get("root_folder", "N/A"))
                file_count = len(entry.get("selected_files", []))
                
                prompt_text = entry.get("prompt_text", "").strip()
                if not prompt_text:
                    prompt_preview = "(üres prompt)"
                else:
                    prompt_preview = ' '.join(prompt_text.split())[:140]
                    if len(prompt_text) > 140:
                        prompt_preview += "..."

                display_values.append(f"{ts} | {prompt_preview} | {folder_name} ({file_count}f)")
            except: 
                display_values.append("Invalid Entry")

        self.history_combobox['values'] = display_values
        if not self.history_entries:
            self.history_combobox.set("")

    def get_selected_content(self):
        final_output_parts = []
        
        if self.copy_prompt_var.get():
            prompt_content = self.editable_prompt_text.get("1.0", tk.END).strip()
            if prompt_content:
                final_output_parts.append(prompt_content)
        
        if self.copy_global_prompt_var.get():
            global_prefix = self.preferences.get("global_prefix", "").strip()
            if global_prefix:
                final_output_parts.append(global_prefix)

        selected_relative_paths_str = self.selected_listbox.get(0, tk.END)
        if selected_relative_paths_str:
            if final_output_parts:
                final_output_parts.append("\n\n// --- Kód Kontextus alább --- \n")
            
            root_folder = self.selected_folder.get()
            if not root_folder: return "### Hiba: Nincs gyökérmappa kiválasztva ###"
            base_path = pathlib.Path(root_folder)
            files_to_process = sorted([base_path / p for p in selected_relative_paths_str if (base_path / p).is_file()])
            
            for file_path in files_to_process:
                try:
                    relative_path = file_path.relative_to(base_path)
                    header = f"// --- Fájl: {relative_path.as_posix()} ---"
                    final_output_parts.append(header)
                    content = ""
                    encodings = ['utf-8', 'cp1250', 'cp1252', 'latin1']
                    for enc in encodings:
                        try:
                            with open(file_path, 'r', encoding=enc) as f: content = f.read()
                            break
                        except UnicodeDecodeError: continue
                    else: content = f"### Hiba: Fájl nem olvasható ({relative_path.as_posix()}) ###"
                    final_output_parts.append(content.strip())
                except Exception as e:
                    final_output_parts.append(f"// --- Hiba feldolgozáskor: {file_path} ({e}) ---")
                    
        return "\n\n".join(final_output_parts)
    
    def copy_to_clipboard(self):
        content = self.get_selected_content()
        if not content.strip(): 
            messagebox.showinfo("Információ", "Nincs másolható tartalom (se fájl, se prompt)."); return
        self.save_history()
        try:
            self.root.clipboard_clear(); self.root.clipboard_append(content)
            self.status_text.set(f"Tartalom másolva ({self.char_count.get()} kar., ~{self.token_count.get()} token). Előzmény mentve.")
        except tk.TclError: messagebox.showerror("Hiba", "Nem sikerült a vágólapra másolni...")
        except Exception as e: messagebox.showerror("Hiba", f"Váratlan hiba: {e}")

    def save_to_file(self):
        content = self.get_selected_content()
        if not content.strip(): 
            messagebox.showinfo("Információ", "Nincs menthető tartalom (se fájl, se prompt)."); return
        self.save_history()
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt", filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")], title="Kontextus mentése fájlba"
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f: f.write(content)
                self.status_text.set(f"Fájl mentve: {os.path.basename(filename)}. Előzmény mentve.")
            except Exception as e:
                messagebox.showerror("Mentési Hiba", f"Hiba: {e}"); self.status_text.set("Mentési hiba.")

    def get_current_extensions(self):
        return [ext for ext, var in self.extension_vars.items() if var.get()]

    def get_current_ignore_patterns(self):
        ignore_string = self.ignore_text.get("1.0", tk.END).strip()
        return [pattern.strip() for pattern in ignore_string.splitlines() if pattern.strip()]

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder: self.selected_folder.set(folder); self.apply_filters()

    def apply_filters(self):
        self.files_to_preserve_on_reload = set(self.selected_listbox.get(0, tk.END))
        folder = self.selected_folder.get()
        if not folder or not os.path.isdir(folder): messagebox.showwarning("Hiba", "Valid mappa kell."); return
        self.status_text.set("Szkennelés és szűrés..."); self.root.update_idletasks()
        for i in self.tree.get_children(): self.tree.delete(i)
        self.selected_listbox.delete(0, tk.END); self.preview_text_update(None)
        self.listbox_history = [()]
        self.listbox_history_index = 0
        self._update_undo_redo_buttons_state()
        self.char_count.set(0); self.token_count.set(0); self.all_tree_items_data = []; self.all_tree_items_map = {}; self.file_path_to_iid_map = {}
        self.search_term.set(""); self.search_in_content_var.set(False)
        extensions = self.get_current_extensions(); ignore_patterns = self.get_current_ignore_patterns()
        self.current_gitignore_matcher = None
        gitignore_path = os.path.join(folder, ".gitignore")
        if gitignore_parser_available and os.path.exists(gitignore_path):
            try:
                base_path = pathlib.Path(folder)
                self.current_gitignore_matcher = gitignore_parser.parse(gitignore_path, base_path)
                self.status_text.set("Szkennelés és szűrés (.gitignore)...")
            except Exception as e: print(f"Gitignore hiba: {e}"); self.status_text.set("Szkennelés (gitignore hiba)...")
        else: self.status_text.set("Szkennelés és szűrés...")
        self.scan_thread = threading.Thread(target=self.scan_folder_thread, args=(folder, extensions, ignore_patterns), daemon=True); self.scan_thread.start()

    def scan_folder_thread(self, folder_path, extensions, ignore_patterns):
        root_path = pathlib.Path(folder_path); items_data = []; parent_map = {str(root_path): ''}
        items_data.append(('', 'folder', root_path.name, str(root_path)))
        for root, dirs, files in os.walk(folder_path, topdown=True):
            current_path = pathlib.Path(root)
            dirs[:] = [d for d in dirs if not self.is_ignored(current_path / d, ignore_patterns)]
            parent_id = parent_map.get(str(current_path))
            if parent_id is None: continue
            
            for dirname in dirs:
                dir_full_path = current_path / dirname
                item_id = str(dir_full_path)
                items_data.append((parent_id, 'folder', dirname, item_id))
                parent_map[item_id] = item_id
            
            for filename in files:
                file_full_path = current_path / filename
                if not any(filename.lower().endswith(ext) for ext in extensions): continue
                if self.is_ignored(file_full_path, ignore_patterns): continue
                item_id = str(file_full_path)
                items_data.append((parent_id, 'file', filename, item_id))
                
        self.update_queue.put(('store_and_populate_tree', items_data))
        self.update_queue.put(('scan_complete', None))
    
    def is_ignored(self, path: pathlib.Path, custom_ignore_patterns):
        if self.current_gitignore_matcher and self.current_gitignore_matcher(path):
            return True

        root_path_str = self.selected_folder.get()
        if not root_path_str:
            return False
        
        root_path = pathlib.Path(root_path_str)
        
        try:
            relative_path_posix = path.relative_to(root_path).as_posix()
        except ValueError:
            relative_path_posix = None

        for pattern in custom_ignore_patterns:
            if '*' in pattern or '?' in pattern:
                if path.match(pattern):
                    return True
                continue

            if '/' in pattern or '\\' in pattern:
                normalized_pattern = pattern.replace('\\', '/')
                if relative_path_posix:
                    if relative_path_posix == normalized_pattern or relative_path_posix.startswith(normalized_pattern + '/'):
                        return True
                continue

            if path.name == pattern:
                return True
                
        return False
        
    def process_update_queue(self):
        try:
            while True:
                message_type, data = self.update_queue.get_nowait()
                if message_type == 'store_and_populate_tree':
                    self.all_tree_items_data = data
                    self.all_tree_items_map = {item[3]: (item[0], item[1], item[2]) for item in data}
                    self.file_path_to_iid_map = {item[3]: item[3] for item in data}
                    self.filter_treeview()

                    root_path = self.selected_folder.get()
                    if root_path and self.files_to_preserve_on_reload:
                        base_path = pathlib.Path(root_path)
                        all_valid_files_after_filter = {
                            pathlib.Path(item[3]).relative_to(base_path).as_posix()
                            for item in self.all_tree_items_data if item[1] == 'file'
                        }
                        surviving_files = self.files_to_preserve_on_reload.intersection(all_valid_files_after_filter)

                        if surviving_files:
                            for file_path in sorted(list(surviving_files)):
                                self.selected_listbox.insert(tk.END, file_path)
                            self.update_listbox_based_counts()
                            self._save_listbox_state()
                    self.files_to_preserve_on_reload = set()
                    self.status_text.set("Fa feltöltve.")
                elif message_type == 'scan_complete': self.status_text.set("Szkennelés befejezve.")
                elif message_type == 'update_counts':
                    chars, tokens = data; self.char_count.set(chars); self.token_count.set(tokens)
                    self.status_text.set("Lista és számlálók frissítve.")
                elif message_type == 'update_preview': self.preview_text_update(data)
                elif message_type == 'status': self.status_text.set(data)
                self.update_queue.task_done()
        except queue.Empty: pass
        finally: self.root.after(100, self.process_update_queue)

    def _populate_tree_from_data(self, items_data):
        self.tree.delete(*self.tree.get_children())
        item_map = {item[3]: item for item in items_data}
        
        processed_iids = set()
        for _, _, _, item_iid in items_data:
            self._insert_item_with_parents(item_iid, item_map, processed_iids)

    def _insert_item_with_parents(self, item_iid, item_map, processed_iids):
        if item_iid in processed_iids:
            return
        
        item_data = item_map.get(item_iid)
        if not item_data:
            processed_iids.add(item_iid)
            return

        parent_id, item_type, display_name, full_path = item_data
        
        if parent_id and parent_id not in processed_iids:
            self._insert_item_with_parents(parent_id, item_map, processed_iids)

        if not self.tree.exists(item_iid):
            try:
                self.tree.insert(parent_id, 'end', iid=item_iid, text=display_name, values=(full_path, item_type), open=False)
            except tk.TclError:
                pass
        
        processed_iids.add(item_iid)

    def _get_all_descendants(self, folder_id):
        descendants = set()
        children = [item for item in self.all_tree_items_data if item[0] == folder_id]
        for _, _, _, child_id in children:
            descendants.add(child_id)
            if self.all_tree_items_map.get(child_id, (None, 'file', None))[1] == 'folder':
                descendants.update(self._get_all_descendants(child_id))
        return descendants
    
    def exclude_selected_from_tree(self):
        selected_ids = self.tree.selection()
        if not selected_ids:
            self.status_text.set("Nincs elem kijelölve a kizáráshoz.")
            return

        root_folder = self.selected_folder.get()
        if not root_folder:
            messagebox.showerror("Hiba", "Nincs projekt mappa kiválasztva a relatív útvonal meghatározásához.")
            return
        base_path = pathlib.Path(root_folder)

        current_ignores = self.get_current_ignore_patterns()
        new_ignores_to_add = set()

        for item_id in selected_ids:
            try:
                full_path_str = self.tree.item(item_id, 'values')[0]
                full_path = pathlib.Path(full_path_str)
                
                relative_path = full_path.relative_to(base_path).as_posix()

                if relative_path and relative_path not in current_ignores:
                    new_ignores_to_add.add(relative_path)
            except (IndexError, ValueError) as e:
                print(f"Hiba a relatív útvonal meghatározásakor az elemhez '{item_id}': {e}")
                display_name = self.tree.item(item_id, 'text')
                if display_name and display_name not in current_ignores:
                    new_ignores_to_add.add(display_name)

        if new_ignores_to_add:
            updated_ignores = current_ignores + sorted(list(new_ignores_to_add))
            self.ignore_text.delete("1.0", tk.END)
            self.ignore_text.insert("1.0", "\n".join(updated_ignores))
            self.status_text.set(f"{len(new_ignores_to_add)} új kizárás hozzáadva. Újratöltés...")
            self.apply_filters()
        else:
            self.status_text.set("A kijelölt elemek már a kizárási listán vannak.")

    def remove_selected_from_list(self):
        selected_indices = self.selected_listbox.curselection()
        if not selected_indices: self.status_text.set("Nincs elem kiválasztva a listában."); return
        removed_count = len(selected_indices)
        for index in sorted(selected_indices, reverse=True): self.selected_listbox.delete(index)
        self.status_text.set(f"{removed_count} fájl eltávolítva."); self.update_listbox_based_counts()
        self._save_listbox_state()

    def clear_selection_list(self):
        list_size = self.selected_listbox.size()
        if list_size > 0:
            self.selected_listbox.delete(0, tk.END); self.update_listbox_based_counts()
            self.status_text.set(f"Lista ({list_size} elem) törölve.")
            self._save_listbox_state()
        else:
            self.status_text.set("Lista már üres.")

    def on_tree_selection_change(self, event=None):
        selected_ids = self.tree.selection()
        if len(selected_ids) == 1:
            item_id = selected_ids[0]
            values = self.tree.item(item_id, 'values')
            if values and len(values) > 1 and values[1] == 'file':
                 file_path = values[0]
                 self._read_file_for_preview(file_path)
                 return
        self.preview_text_update(None)
        
    def on_listbox_selection_change(self, event=None):
        cur_sel = self.selected_listbox.curselection()
        if not cur_sel or len(cur_sel) != 1: return
        selected_rel_path = self.selected_listbox.get(cur_sel[0])
        root_folder = self.selected_folder.get()
        if not root_folder: return
        abs_path = str(pathlib.Path(root_folder) / selected_rel_path)
        self.tree.selection_set()
        if abs_path in self.file_path_to_iid_map:
            item_iid = self.file_path_to_iid_map[abs_path]
            if self.tree.exists(item_iid):
                parent_id = self.tree.parent(item_iid)
                while parent_id:
                    self.tree.item(parent_id, open=True)
                    parent_id = self.tree.parent(parent_id)
                self.tree.selection_set(item_iid); self.tree.see(item_iid)
                self._read_file_for_preview(abs_path)
                self.status_text.set(f"Fájl kiválasztva: {selected_rel_path}")
            else:
                self.status_text.set(f"Fájl nem látható (szűrés aktív?): {selected_rel_path}")
                self.preview_text_update(None)
        else:
            self.status_text.set(f"Fájl nem található: {selected_rel_path}")
            self.preview_text_update(None)

    def _read_file_for_preview(self, file_path):
        threading.Thread(target=self._read_file_for_preview_thread, args=(file_path,), daemon=True).start()

    def _read_file_for_preview_thread(self, file_path):
        try:
            content = ""
            encodings = ['utf-8', 'cp1250', 'cp1252', 'latin1']
            for enc in encodings:
                try:
                    with open(file_path, 'r', encoding=enc) as f: content = f.read(PREVIEW_MAX_CHARS)
                    break
                except UnicodeDecodeError: continue
            else: content = f"### Hiba: Nem sikerült dekódolni a fájlt ({os.path.basename(file_path)}) ###"
            if len(content) >= PREVIEW_MAX_CHARS: content += "\n\n[... Fájl vége levágva az előnézetben ...]"
            self.update_queue.put(('update_preview', content))
        except Exception as e:
            self.update_queue.put(('update_preview', f"### Hiba az előnézetben: {e} ###"))

    def preview_text_update(self, content):
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        if content: self.preview_text.insert("1.0", content)
        self.preview_text.config(state=tk.DISABLED)

    def find_related_references(self):
        search_depth = self.ref_search_depth.get()
        if search_depth == 0:
            self.status_text.set("Referencia keresés mélysége 0, nincs művelet.")
            return

        target_extensions = {".cs", ".razor", ".cshtml"}
        root_folder = self.selected_folder.get()
        if not root_folder:
            messagebox.showerror("Hiba", "Nincs projekt mappa kiválasztva.")
            return
        base_path = pathlib.Path(root_folder)

        initial_selected_ids = set()
        tree_selection = self.tree.selection()
        list_selection_indices = self.selected_listbox.curselection()

        if tree_selection:
            initial_selected_ids.update(tree_selection)
        if list_selection_indices:
            for i in list_selection_indices:
                rel_path = self.selected_listbox.get(i)
                abs_path = str(base_path / rel_path)
                if abs_path in self.file_path_to_iid_map:
                    initial_selected_ids.add(self.file_path_to_iid_map[abs_path])

        if not initial_selected_ids:
            messagebox.showinfo("Információ", "Válassz ki C# vagy Razor fájl(oka)t a fában vagy a listában a keresés indításához.")
            return

        start_files_abs = set()
        for item_id in initial_selected_ids:
            item_values = self.tree.item(item_id, 'values')
            if not item_values: continue
            full_path, item_type = item_values

            if item_type == 'file' and pathlib.Path(full_path).suffix.lower() in target_extensions:
                start_files_abs.add(full_path)
            elif item_type == 'folder':
                for descendant_id in self._get_all_descendants(item_id):
                    desc_item = self.all_tree_items_map.get(descendant_id)
                    if desc_item and desc_item[1] == 'file' and pathlib.Path(descendant_id).suffix.lower() in target_extensions:
                        start_files_abs.add(descendant_id)

        if not start_files_abs:
            messagebox.showinfo("Információ", "A kiválasztás nem tartalmaz C# vagy Razor fájlokat.")
            return

        self.status_text.set(f"Referenciák keresése... (Mélység: {search_depth})"); self.root.update_idletasks()

        files_to_scan_next = set(start_files_abs)
        all_found_files_abs = set()
        all_scanned_files_abs = set()

        for i in range(search_depth):
            if not files_to_scan_next:
                break
            
            self.status_text.set(f"Keresés, {i+1}. szint... ({len(files_to_scan_next)} fájl)")
            self.root.update_idletasks()
            
            current_level_files_to_scan = files_to_scan_next - all_scanned_files_abs
            files_to_scan_next = set()
            potential_type_names = set()

            for file_path in current_level_files_to_scan:
                all_scanned_files_abs.add(file_path)
                try:
                    content = self._read_file_content_safely(file_path)
                    
                    if content:
                        found_constructs = set(re.findall(POTENTIAL_TYPE_REGEX, content))
                        for construct in found_constructs:
                            clean_construct = re.sub(r'[^a-zA-Z0-9_]', ' ', construct)
                            for name in clean_construct.split():
                                if name and name[0].isupper() and \
                                   not re.fullmatch(CSHARP_KEYWORDS_REGEX, name) and \
                                   not re.fullmatch(CSHARP_COMMON_TYPES_REGEX, name):
                                    potential_type_names.add(name)
                except Exception as e:
                    print(f"Hiba a ref. kereséshez fájl olvasásakor {file_path}: {e}")

            if not potential_type_names:
                continue

            for type_name in potential_type_names:
                target_filenames = {f"{type_name}.cs", f"{type_name}.razor", f"{type_name}.cshtml", f"I{type_name}.cs"}
                for _, _, disp_name, full_path in self.all_tree_items_data:
                    if disp_name in target_filenames:
                        if full_path not in all_scanned_files_abs:
                            files_to_scan_next.add(full_path)
                        all_found_files_abs.add(full_path)
        
        if not all_found_files_abs:
            self.status_text.set("Nem található új kapcsolódó fájl.")
            return

        found_ref_files_rel = set()
        for abs_path in all_found_files_abs:
            try:
                found_ref_files_rel.add(pathlib.Path(abs_path).relative_to(base_path).as_posix())
            except ValueError:
                pass
        
        current_list_items = set(self.selected_listbox.get(0, tk.END))
        start_files_rel = {pathlib.Path(p).relative_to(base_path).as_posix() for p in start_files_abs}
        
        newly_added = found_ref_files_rel - current_list_items - start_files_rel
        
        if newly_added:
            all_items = sorted(list(current_list_items.union(newly_added)))
            self.selected_listbox.delete(0, tk.END)
            for rel_path in all_items:
                self.selected_listbox.insert(tk.END, rel_path)
            self.status_text.set(f"{len(newly_added)} új kapcsolódó fájl hozzáadva.")
            self.update_listbox_based_counts()
            self._save_listbox_state()
        else:
            self.status_text.set("Nem található új kapcsolódó fájl (már listázva vagy a kiindulási fájlok részei).")

    def update_listbox_based_counts(self):
        threading.Thread(target=self.update_counts_thread, daemon=True).start()

    def update_counts_thread(self):
        selected_relative_paths_str = self.selected_listbox.get(0, tk.END)
        root_folder = self.selected_folder.get()
        if not root_folder:
            self.update_queue.put(('update_counts', (0,0)))
            return
        base_path = pathlib.Path(root_folder)
        absolute_paths_to_count = [str(base_path / p) for p in selected_relative_paths_str if (base_path / p).is_file()]
        total_chars = 0
        for file_path in absolute_paths_to_count:
            try:
                total_chars += os.path.getsize(file_path)
            except Exception as e: print(f"Hiba a fájl méretének olvasásakor ({file_path}): {e}")
        total_tokens_est = (total_chars + CHARS_PER_TOKEN_ESTIMATE - 1) // CHARS_PER_TOKEN_ESTIMATE if CHARS_PER_TOKEN_ESTIMATE > 0 else total_chars
        self.update_queue.put(('update_counts', (total_chars, total_tokens_est)))

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    try: style.theme_use('vista')
    except tk.TclError:
        try: style.theme_use('clam')
        except tk.TclError: pass
    app = LLMContextCollectorApp(root)
    root.mainloop()