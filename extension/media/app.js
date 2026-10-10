/* All untrusted API text is inserted with textContent, never HTML. */
const vscode = acquireVsCodeApi();
const app = document.getElementById("app");
let viewVersion = 0,
  refreshDashboard = null;
let serial = 0,
  pending = new Map(),
  state = {
    user: null,
    projects: [],
    project: null,
    page: "Overview",
    bug: null,
  },
  poll;
function bridge(type, fields = {}) {
  return new Promise((resolve, reject) => {
    const id = ++serial;
    pending.set(id, { resolve, reject });
    vscode.postMessage({ id, type, ...fields });
  });
}
window.addEventListener("message", (event) => {
  const message = event.data;
  const item = pending.get(message.id);
  if (item) {
    pending.delete(message.id);
    message.error
      ? item.reject(new Error(message.error))
      : item.resolve(message.result);
  }
});
const api = (path, method = "GET", body) =>
  bridge("request", { path, method, body });
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, action, secondary = false) {
  const b = el("button", text, secondary ? "secondary" : "");
  b.type = "button";
  b.onclick = async () => {
    b.disabled = true;
    try {
      await action();
    } catch (e) {
      error(e);
    } finally {
      b.disabled = false;
    }
  };
  return b;
}
function notice(text, kind = "") {
  return el("div", text, "notice " + kind);
}
function error(e) {
  let region = document.getElementById("messages");
  if (!region) {
    region = el("div");
    app.prepend(region);
  }
  region.replaceChildren(notice(e.message || String(e), "error"));
  region.setAttribute("role", "alert");
}
function field(form, label, name, type = "text", value = "", required = true) {
  const id = "field-" + ++serial;
  const l = el("label", label);
  l.htmlFor = id;
  const input = el(
    type === "textarea" ? "textarea" : type === "select" ? "select" : "input",
  );
  if (input.tagName === "INPUT") input.type = type;
  input.id = id;
  input.name = name;
  input.required = required;
  if (value !== undefined) input.value = value;
  form.append(l, input);
  return input;
}
function options(select, values, selected) {
  for (const value of values) {
    const option = el(
      "option",
      typeof value === "object" ? value.label : value,
    );
    option.value = typeof value === "object" ? value.value : value;
    select.append(option);
  }
  if (selected !== undefined && selected !== null)
    select.value = String(selected);
  return select;
}
function submit(form, text, handler) {
  const b = el("button", text);
  b.type = "submit";
  const actions = el("div", undefined, "actions");
  actions.append(b);
  form.append(actions);
  form.onsubmit = async (event) => {
    event.preventDefault();
    b.disabled = true;
    try {
      await handler(Object.fromEntries(new FormData(form)));
    } catch (e) {
      error(e);
    } finally {
      b.disabled = false;
    }
  };
}
function table(headers, rows) {
  const wrap = el("div", undefined, "scroll"),
    t = el("table"),
    head = el("tr");
  for (const h of headers) head.append(el("th", h));
  const thead = el("thead");
  thead.append(head);
  t.append(thead);
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    for (const value of row) {
      const td = el("td");
      td.append(
        value instanceof Node
          ? value
          : document.createTextNode(
              value === null || value === undefined ? "—" : String(value),
            ),
      );
      tr.append(td);
    }
    body.append(tr);
  }
  t.append(body);
  wrap.append(t);
  return wrap;
}
const projectPath = () => "/projects/" + state.project;
function message(text) {
  document.getElementById("messages")?.replaceChildren(notice(text));
}
function showAuth(mode = "login") {
  clearInterval(poll);
  app.replaceChildren();
  const main = el("main", undefined, "auth");
  app.append(main);
  main.append(
    el("h1", "Bug Triage"),
    el("p", "Keep bug reporting and triage inside your editor.", "muted"),
  );
  const messages = el("div");
  messages.id = "messages";
  messages.setAttribute("aria-live", "polite");
  main.append(messages);
  const form = el("form");
  main.append(form);
  if (mode === "register") field(form, "Display name", "name");
  if (mode !== "verify") field(form, "Email address", "email", "email");
  if (["login", "register"].includes(mode)) {
    const input = field(form, "Password", "password", "password");
    input.autocomplete = mode === "login" ? "current-password" : "new-password";
    if (mode === "register") {
      input.minLength = 8;
      form.append(
        el(
          "p",
          "At least 8 characters, an uppercase letter, a number, and a special character.",
          "muted",
        ),
      );
    }
  }
  if (mode === "verify")
    field(form, "Verification code from your email", "token");
  submit(
    form,
    {
      login: "Sign in",
      register: "Create account",
      verify: "Verify email",
      resend: "Resend verification",
    }[mode],
    async (data) => {
      if (mode === "login") {
        await bridge("login", { body: data });
        await boot();
      } else {
        const result = await api(
          "/auth/" +
            (mode === "register"
              ? "register"
              : mode === "verify"
                ? "verify"
                : "resend"),
          "POST",
          data,
        );
        showAuth(mode === "register" ? "verify" : "login");
        message(result.message);
      }
    },
  );
  const actions = el("div", undefined, "actions");
  for (const [name, label] of [
    ["login", "Sign in"],
    ["register", "Register"],
    ["verify", "Verify email"],
    ["resend", "Resend code"],
  ])
    if (name !== mode)
      actions.append(button(label, () => showAuth(name), true));
  main.append(actions);
}
async function boot() {
  try {
    state.user = await api("/auth/me");
    state.projects = await api("/projects");
    if (!state.projects.some((p) => p.id === state.project))
      state.project = state.projects[0]?.id ?? null;
    await render();
    clearInterval(poll);
    poll = setInterval(async () => {
      try {
        const n = await api("/notifications");
        const b = document.getElementById("notifications-tab");
        if (b)
          b.textContent =
            "Notifications" + (n.unread ? " (" + n.unread + ")" : "");
        if (refreshDashboard) await refreshDashboard();
      } catch {}
    }, 15000);
  } catch {
    showAuth();
  }
}
async function render() {
  refreshDashboard = null;
  app.replaceChildren();
  const header = el("header"),
    brand = el("div");
  brand.append(
    el("h1", "Bug Triage"),
    el("p", "REPORT · UNDERSTAND · RESOLVE"),
  );
  header.append(brand);
  const identity = el(
    "div",
    state.user.name + " · " + state.user.global_role,
    "identity",
  );
  header.append(
    identity,
    button(
      "Sign out",
      async () => {
        await bridge("logout");
        showAuth();
      },
      true,
    ),
  );
  app.append(header);
  const nav = el("nav");
  nav.setAttribute("aria-label", "Workspace sections");
  for (const page of [
    "Overview",
    "Bugs",
    "Report bug",
    "Team",
    "Notifications",
    "Settings",
    ...(state.user.global_role === "admin" ? ["Admin"] : []),
  ]) {
    const b = button(
      page,
      async () => {
        state.page = page;
        await render();
      },
      true,
    );
    if (page === state.page) b.setAttribute("aria-current", "page");
    if (page === "Notifications") b.id = "notifications-tab";
    nav.append(b);
  }
  app.append(nav);
  const main = el("main"),
    messages = el("div");
  messages.id = "messages";
  messages.setAttribute("aria-live", "polite");
  main.append(messages);
  app.append(main);
  const row = el("div", undefined, "row"),
    label = el("label", "Project");
  label.htmlFor = "project-picker";
  const picker = el("select");
  picker.id = "project-picker";
  picker.setAttribute("aria-label", "Current project");
  options(
    picker,
    state.projects.map((p) => ({
      value: p.id,
      label: p.name + (p.archived ? " (archived)" : ""),
    })),
    state.project,
  );
  picker.onchange = async () => {
    state.project = Number(picker.value);
    await render();
  };
  row.append(label, picker);
  if (["manager", "admin"].includes(state.user.global_role))
    row.append(button("New project", () => projectForm(main), true));
  main.append(row, el("h2", state.page));
  try {
    if (
      ["Overview", "Bugs", "Report bug", "Team"].includes(state.page) &&
      !state.project
    ) {
      main.append(
        notice(
          "Create a project or ask a project manager to add you to a team.",
        ),
      );
      return;
    }
    await {
      Overview: overview,
      Bugs: bugs,
      "Report bug": report,
      Team: team,
      Notifications: notifications,
      Settings: settings,
      Admin: adminPage,
    }[state.page](main);
  } catch (e) {
    error(e);
  }
}
function projectForm(main) {
  const form = el("form");
  field(form, "Project name", "name");
  submit(form, "Create project", async (data) => {
    const result = await api("/projects", "POST", data);
    state.project = result.id;
    await boot();
  });
  main.prepend(form);
  form.querySelector("input").focus();
}
async function overview(main) {
  const project = state.project,
    region = el("section");
  region.setAttribute("aria-label", "Project dashboard");
  main.append(region);
  const refresh = async () => {
    const data = await api("/projects/" + project + "/dashboard");
    if (!region.isConnected) return;
    const grid = el("div", undefined, "metrics");
    for (const [label, value] of Object.entries({
      ...data.counts,
      "Active critical": data.critical,
    })) {
      const card = el("div", undefined, "metric");
      card.append(el("strong", value), el("span", label));
      grid.append(card);
    }
    region.replaceChildren(
      grid,
      el("h3", "Assignment readiness"),
      notice(
        data.model.cold_start
          ? `${data.model.remaining} more verified, assigned bugs needed before model training. Declared skills can support rule-based suggestions.`
          : `Model status: ${data.model.status}. Last trained: ${data.model.trained_at || "Not yet trained"}`,
      ),
      el("h3", "Activity over eight weeks"),
      trendChart(data.weeks),
      table(
        ["Week", "Reported", "Resolved"],
        data.weeks.map((w) => [w.week, w.reported, w.resolved]),
      ),
      el("h3", "Average resolution time"),
      table(
        ["Severity", "Hours"],
        Object.entries(data.average_resolution_seconds).map(([k, v]) => [
          k,
          v === null ? "No resolved bugs" : (v / 3600).toFixed(2),
        ]),
      ),
    );
  };
  await refresh();
  refreshDashboard = refresh;
  const members = await api(projectPath() + "/members");
  const me = members.find((m) => m.user_id === state.user.id);
  if (state.user.global_role === "admin" || me?.role === "manager") {
    const form = el("form");
    field(
      form,
      "Rename project",
      "name",
      "text",
      state.projects.find((p) => p.id === state.project).name,
    );
    submit(form, "Save project name", async (data) => {
      await api(projectPath(), "PATCH", data);
      await boot();
    });
    main.append(
      form,
      button(
        "Archive project",
        async () => {
          await api(projectPath() + "/archive", "POST");
          await boot();
        },
        true,
      ),
    );
  }
}
async function bugs(main) {
  const form = el("form"),
    row = el("div", undefined, "row");
  form.append(row);
  field(row, "Search title or description", "q", "text", "", false);
  options(field(row, "Status", "status", "select", "", false), [
    "",
    "Open",
    "In Progress",
    "Resolved",
    "Verified",
    "Closed",
  ]);
  options(field(row, "Severity", "severity", "select", "", false), [
    "",
    "Low",
    "Medium",
    "High",
    "Critical",
    "Unclassified",
  ]);
  field(row, "Assignee ID", "assignee_id", "number", "", false);
  field(
    form,
    "Reported from (UTC)",
    "created_from",
    "datetime-local",
    "",
    false,
  );
  field(
    form,
    "Reported before (UTC)",
    "created_to",
    "datetime-local",
    "",
    false,
  );
  const list = el("div");
  let offset = 0,
    current = {};
  const load = async () => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(current))
      if (value)
        params.set(key, key.startsWith("created_") ? value + ":00Z" : value);
    params.set("offset", offset);
    const rows = await api(projectPath() + "/bugs?" + params);
    list.replaceChildren(
      table(
        ["Bug", "Severity", "Status", "Assignee"],
        rows.map((b) => [
          button("#" + b.id + " " + b.title, () => detail(main, b.id), true),
          b.severity,
          b.status,
          b.assignee_id,
        ]),
      ),
    );
    if (!rows.length) list.append(notice("No bugs match these filters."));
    const controls = el("div", undefined, "actions");
    if (offset)
      controls.append(
        button(
          "Previous",
          async () => {
            offset = Math.max(0, offset - 50);
            await load();
          },
          true,
        ),
      );
    if (rows.length === 50)
      controls.append(
        button(
          "Next",
          async () => {
            offset += 50;
            await load();
          },
          true,
        ),
      );
    list.append(controls);
  };
  submit(form, "Search", async (data) => {
    offset = 0;
    current = data;
    await load();
  });
  main.append(form, list);
  await load();
}
async function report(main) {
  const form = el("form");
  const title = field(form, "Title", "title");
  const desc = field(form, "Description", "description", "textarea");
  desc.minLength = 20;
  field(form, "Steps to reproduce", "steps", "textarea");
  field(form, "Environment and version", "environment");
  field(form, "Component", "component", "text", "general");
  field(
    form,
    "Duplicate of bug ID (optional)",
    "duplicate_of",
    "number",
    "",
    false,
  );
  const candidates = el("div");
  candidates.setAttribute("aria-live", "polite");
  form.append(candidates);
  let timer,
    request = 0;
  const check = () => {
    clearTimeout(timer);
    const sequence = ++request;
    if (desc.value.trim().length < 20) {
      candidates.replaceChildren();
      return;
    }
    timer = setTimeout(async () => {
      try {
        const data = {
          title: title.value || "Untitled",
          description: desc.value,
          steps: "Pending",
          environment: "Pending",
        };
        const response = await api(projectPath() + "/duplicates", "POST", data);
        if (sequence !== request || !form.isConnected) return;
        candidates.replaceChildren(el("h3", "Possible duplicates"));
        if (response.warning)
          candidates.append(el("p", response.warning, "muted"));
        for (const item of response.candidates)
          candidates.append(
            button(
              "#" +
                item.id +
                " " +
                item.title +
                (item.similarity_percent === null
                  ? " · lexical match"
                  : " · " + item.similarity_percent + "% similarity"),
              () => detail(main, item.id),
              true,
            ),
          );
      } catch (e) {
        if (sequence === request)
          candidates.replaceChildren(
            notice("Duplicate check unavailable. You can still submit."),
          );
      }
    }, 600);
  };
  desc.oninput = check;
  title.oninput = check;
  submit(form, "Submit bug", async (data) => {
    data.duplicate_of = data.duplicate_of ? Number(data.duplicate_of) : null;
    const response = await api(projectPath() + "/bugs", "POST", data);
    await detail(main, response.bug.id);
  });
  main.append(form);
}
async function detail(main, id) {
  const path = projectPath() + "/bugs/" + id;
  const sequence = ++viewVersion;
  const [data, members, attachments] = await Promise.all([
    api(path),
    api(projectPath() + "/members"),
    api(path + "/attachments"),
  ]);
  if (sequence !== viewVersion || !main.isConnected) return;
  const b = data.bug;
  main.replaceChildren();
  const messages = el("div");
  messages.id = "messages";
  messages.setAttribute("aria-live", "polite");
  main.append(
    messages,
    button(
      "Back to bugs",
      async () => {
        state.page = "Bugs";
        await render();
      },
      true,
    ),
    el("h2", "#" + b.id + " " + b.title),
  );
  const tags = el("div", undefined, "row");
  for (const value of [b.status, b.severity, b.component])
    tags.append(el("span", value, "badge"));
  main.append(
    tags,
    el("h3", "Description"),
    el("p", b.description),
    el("h3", "Steps to reproduce"),
    el("pre", b.steps),
    el("h3", "Environment"),
    el("p", b.environment),
  );
  if (b.duplicate_of)
    main.append(
      button(
        "Original bug #" + b.duplicate_of,
        () => detail(main, b.duplicate_of),
        true,
      ),
    );
  if (b.triage?.message) main.append(notice(b.triage.message));
  const role =
    state.user.global_role === "admin"
      ? "manager"
      : members.find((m) => m.user_id === state.user.id)?.role;
  if (["developer", "manager"].includes(role)) {
    const form = el("form");
    field(form, "Edit title", "title", "text", b.title);
    field(form, "Edit description", "description", "textarea", b.description);
    field(form, "Edit reproduction steps", "steps", "textarea", b.steps);
    field(form, "Edit environment", "environment", "text", b.environment);
    options(
      field(form, "Status", "status", "select"),
      ["Open", "In Progress", "Resolved", "Verified", "Closed"],
      b.status,
    );
    options(
      field(form, "Severity", "severity", "select"),
      ["Unclassified", "Low", "Medium", "High", "Critical"],
      b.severity,
    );
    field(form, "Component", "component", "text", b.component);
    field(
      form,
      "Duplicate of (optional)",
      "duplicate_of",
      "number",
      b.duplicate_of ?? "",
      false,
    );
    if (role === "manager")
      options(
        field(form, "Assign to", "assignee_id", "select", "", false),
        [
          { value: "", label: "Unassigned" },
          ...members.map((m) => ({
            value: m.user_id,
            label: m.name + " (" + m.role + ")",
          })),
        ],
        b.assignee_id ?? "",
      );
    submit(form, "Save changes", async (values) => {
      values.version = b.version;
      values.duplicate_of = values.duplicate_of
        ? Number(values.duplicate_of)
        : null;
      if ("assignee_id" in values)
        values.assignee_id = values.assignee_id
          ? Number(values.assignee_id)
          : null;
      await api(path, "PATCH", values);
      await detail(main, id);
    });
    main.append(form);
  }
  main.append(
    el("h3", "Assignment suggestions · " + data.assignment.mode),
    el("p", data.assignment.message),
  );
  for (const suggestion of data.assignment.recommendations) {
    main.append(
      notice(
        suggestion.name +
          (suggestion.limited_history ? " · limited history" : "") +
          "\n" +
          suggestion.reasons.join(" · "),
      ),
    );
    if (role === "manager")
      main.append(
        button(
          "Assign to " + suggestion.name,
          async () => {
            await api(path, "PATCH", {
              assignee_id: suggestion.user_id,
              version: b.version,
            });
            await detail(main, id);
          },
          true,
        ),
      );
  }
  main.append(el("h3", "Attachments"));
  for (const item of attachments)
    main.append(
      button(
        item.filename + " · " + item.scan_status,
        () =>
          bridge("download", {
            project: state.project,
            bug: id,
            attachment: item.id,
            filename: item.filename,
          }),
        true,
      ),
    );
  main.append(
    button(
      "Attach screenshot or log",
      async () => {
        await bridge("upload", { project: state.project, bug: id });
        await detail(main, id);
      },
      true,
    ),
  );
  main.append(el("h3", "Comments"));
  for (const comment of data.comments)
    main.append(
      el(
        "p",
        (members.find((m) => m.user_id === comment.author_id)?.name ??
          "User #" + comment.author_id) +
          " · " +
          comment.created_at,
      ),
      el("pre", comment.body),
    );
  if (["developer", "manager"].includes(role)) {
    const form = el("form");
    field(form, "Add a comment", "body", "textarea");
    submit(form, "Post comment", async (value) => {
      await api(path + "/comments", "POST", value);
      await detail(main, id);
    });
    main.append(form);
  }
  main.append(
    button(
      "Watch this bug",
      async () => {
        await api(path + "/watch", "PUT");
        message("You are watching this bug.");
      },
      true,
    ),
    button(
      "Stop watching",
      async () => {
        await api(path + "/watch?enabled=false", "PUT");
        message("Watch removed.");
      },
      true,
    ),
    el("h3", "Audit history"),
    table(
      ["When", "Actor", "Action", "Changes"],
      data.audit.map((a) => [
        a.created_at,
        members.find((m) => m.user_id === a.actor_id)?.name ?? a.actor_id,
        a.action,
        JSON.stringify(a.details),
      ]),
    ),
  );
}
async function team(main) {
  const members = await api(projectPath() + "/members"),
    profiles = await api(projectPath() + "/profiles");
  const canManage =
    state.user.global_role === "admin" ||
    members.find((m) => m.user_id === state.user.id)?.role === "manager";
  main.append(
    table(
      ["User ID", "Name", "Role", "Actions"],
      members.map((m) => [
        m.user_id,
        m.name,
        m.role,
        canManage
          ? button(
              "Remove",
              async () => {
                await api(projectPath() + "/members/" + m.user_id, "DELETE");
                await boot();
              },
              true,
            )
          : "�",
      ]),
    ),
  );
  const form = el("form");
  field(form, "User ID", "user_id", "number");
  options(field(form, "Project role", "role", "select"), [
    "reporter",
    "developer",
    "manager",
  ]);
  submit(form, "Add or update membership", async (data) => {
    data.user_id = Number(data.user_id);
    await api(projectPath() + "/members", "PUT", data);
    await render();
  });
  if (canManage) main.append(form);
  main.append(el("h3", "Developer profiles"));
  for (const item of profiles) {
    const p = item.profile;
    main.append(
      el("h3", item.name),
      el(
        "p",
        `${item.workload}/${p.capacity} active bugs · ${p.availability}${p.active ? "" : " · deactivated"}`,
      ),
      el("p", "Skills: " + (p.skills.join(", ") || "Not declared")),
      el("p", "Components: " + (p.components.join(", ") || "Not declared")),
      el("p", item.history.length + " recent verified resolutions"),
      table(
        ["Component", "Severity", "Resolution hours"],
        item.history.map((r) => [
          r.component,
          r.severity,
          (r.resolution_seconds / 3600).toFixed(2),
        ]),
      ),
    );
    if (state.user.global_role === "admin") {
      const f = el("form");
      field(
        f,
        "Skills, comma separated",
        "skills",
        "text",
        p.skills.join(", "),
        false,
      );
      field(
        f,
        "Components, comma separated",
        "components",
        "text",
        p.components.join(", "),
        false,
      );
      options(
        field(f, "Availability", "availability", "select"),
        ["Available", "Busy", "Unavailable"],
        p.availability,
      );
      field(f, "Maximum active bugs", "capacity", "number", p.capacity);
      const active = field(
        f,
        "Profile active",
        "active",
        "checkbox",
        "",
        false,
      );
      active.checked = p.active;
      submit(f, "Save profile", async (values) => {
        await api("/admin" + projectPath() + "/profiles/" + p.user_id, "PUT", {
          skills: values.skills
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
          components: values.components
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
          availability: values.availability,
          capacity: Number(values.capacity),
          active: active.checked,
        });
        await render();
      });
      main.append(f);
    }
  }
}
async function notifications(main) {
  const data = await api("/notifications");
  main.append(el("p", data.unread + " unread notifications"));
  for (const item of data.items) {
    const row = el("div", undefined, "actions");
    row.append(
      button(
        (item.read ? "" : "Unread · ") + item.message,
        async () => {
          state.project = item.project_id;
          await api("/notifications/" + item.id + "/read", "POST");
          await detail(main, item.bug_id);
        },
        true,
      ),
    );
    main.append(row);
  }
  if (!data.items.length) main.append(notice("No notifications yet."));
}
async function settings(main) {
  const form = el("form");
  field(form, "Display name", "name", "text", state.user.name);
  field(form, "Email address", "email", "email", state.user.email);
  field(
    form,
    "Current password (required only to change email)",
    "current_password",
    "password",
    "",
    false,
  );
  form.append(el("h3", "Email preferences"));
  const checks = {};
  for (const key of ["assignment", "status", "comment", "critical"]) {
    const c = field(form, key + " emails", key, "checkbox", "", false);
    c.checked = state.user.preferences?.[key] !== false;
    checks[key] = c;
  }
  submit(form, "Save account settings", async (data) => {
    const body = {
      name: data.name,
      preferences: Object.fromEntries(
        Object.entries(checks).map(([k, v]) => [k, v.checked]),
      ),
    };
    if (data.email !== state.user.email) {
      body.email = data.email;
      body.current_password = data.current_password;
    }
    const result = await api("/auth/me", "PATCH", body);
    state.user = await api("/auth/me");
    message(
      result.email_change_pending
        ? "Verification email queued for the new address. Your current email remains active until verification."
        : "Settings saved.",
    );
  });
  main.append(form);
}
async function adminPage(main) {
  const users = await api("/admin/users"),
    models = await api("/admin/models"),
    config = await api("/admin/settings");
  main.append(
    el("h3", "User administration"),
    table(
      ["ID", "Name", "Email", "Role", "Active"],
      users.map((u) => [u.id, u.name, u.email, u.global_role, u.active]),
    ),
  );
  const uf = el("form");
  options(
    field(uf, "User", "user_id", "select"),
    users.map((u) => ({ value: u.id, label: u.name + " · " + u.email })),
  );
  options(field(uf, "Global role", "global_role", "select"), [
    "reporter",
    "manager",
    "admin",
  ]);
  const active = field(uf, "Account active", "active", "checkbox", "", false);
  active.checked = true;
  submit(uf, "Update account", async (data) => {
    await api("/admin/users/" + data.user_id, "PATCH", {
      active: active.checked,
      global_role: data.global_role,
    });
    await render();
  });
  main.append(
    uf,
    el("h3", "Model state"),
    table(
      ["Project", "Verified", "Remaining", "Status", "Trained"],
      models.map((m) => [
        m.name,
        m.verified_assigned_count,
        m.remaining,
        m.status,
        m.trained_at,
      ]),
    ),
  );
  const form = el("form");
  const threshold = field(
    form,
    "Semantic duplicate threshold",
    "duplicate_threshold",
    "number",
    config.duplicate_threshold,
  );
  threshold.min = 0;
  threshold.max = 1;
  threshold.step = 0.01;
  field(
    form,
    "Verified bugs before assignment training",
    "cold_start_count",
    "number",
    config.cold_start_count,
  );
  const rule = field(
    form,
    "Allow rule-based severity fallback",
    "rule_severity",
    "checkbox",
    "",
    false,
  );
  rule.checked = config.rule_severity;
  submit(form, "Save AI settings", async (data) => {
    await api("/admin/settings", "PUT", {
      duplicate_threshold: Number(data.duplicate_threshold),
      cold_start_count: Number(data.cold_start_count),
      rule_severity: rule.checked,
    });
    message("Settings updated.");
  });
  main.append(form);
}
boot();

function trendChart(weeks) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 800 190");
  svg.setAttribute("role", "img");
  svg.setAttribute(
    "aria-label",
    "Eight-week bug activity. Teal: reported; blue: resolved. Exact values follow in the table.",
  );
  const max = Math.max(1, ...weeks.flatMap((w) => [w.reported, w.resolved]));
  weeks.forEach((w, i) => {
    [w.reported, w.resolved].forEach((value, n) => {
      const r = document.createElementNS(ns, "rect");
      r.setAttribute("x", String(i * 100 + 20 + n * 25));
      r.setAttribute("y", String(150 - (value / max) * 125));
      r.setAttribute("width", "22");
      r.setAttribute("height", String(Math.max(1, (value / max) * 125)));
      r.setAttribute("fill", n ? "#8798b8" : "#39a899");
      svg.append(r);
    });
    const t = document.createElementNS(ns, "text");
    t.setAttribute("x", String(i * 100 + 15));
    t.setAttribute("y", "175");
    t.setAttribute("fill", "currentColor");
    t.setAttribute("font-size", "12");
    t.textContent = w.week.slice(5);
    svg.append(t);
  });
  return svg;
}
