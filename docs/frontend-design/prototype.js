/**
 * 自适应学习前端设计原型角色和页面交互。
 * @Project : adaptive-edu
 * @File : prototype.js
 * @Author : Qintsg
 * @Date : 2026-07-18
 */
const roleSelect = document.querySelector("#role-select");
const viewSelect = document.querySelector("#view-select");
const roleName = document.querySelector("#role-name");
const sidebarUser = document.querySelector("#sidebar-user");
const sidebarAvatar = document.querySelector("#sidebar-avatar");
const topUser = document.querySelector("#top-user");
const topAvatar = document.querySelector("#top-avatar");
const reviewToggle = document.querySelector(".review-dock__toggle");
const reviewPanel = document.querySelector("#review-panel");

const roleConfig = {
  student: {
    label: "学生工作台",
    user: "student1",
    avatar: "S",
    views: [
      ["student-home", "学习工作台"],
      ["student-path", "学习路径"],
      ["student-task", "当前任务"],
      ["student-assessment", "测评"],
      ["student-assignments", "作业"],
      ["student-resources", "课程资源"],
      ["student-graph", "知识图谱"],
      ["student-ai", "AI 学习助手"],
      ["student-agent", "个性化智能体"],
      ["student-courses", "课程与班级"],
      ["student-profile", "学习画像"],
      ["student-settings", "个人设置"],
    ],
  },
  teacher: {
    label: "教师工作台",
    user: "teacher1",
    avatar: "T",
    views: [
      ["teacher-workspace", "课程工作空间"],
      ["teacher-content", "内容工作区"],
      ["teacher-classroom", "班级与学生"],
    ],
  },
  admin: {
    label: "管理工作台",
    user: "admin",
    avatar: "A",
    views: [
      ["admin-governance", "系统概览"],
      ["admin-content", "课程与班级"],
      ["admin-access", "访问与审计"],
    ],
  },
  auth: {
    label: "统一账户入口",
    user: "",
    avatar: "",
    views: [["auth-preview", "认证页"]],
  },
};

/**
 * 替换角色对应的页面选项并返回有效页面。
 *
 * :param role: 当前角色标识。
 * :param preferredView: 优先展示的页面标识。
 * :returns: 实际选中的页面标识。
 */
function replaceViewOptions(role, preferredView) {
  const config = roleConfig[role];
  viewSelect.replaceChildren(
    ...config.views.map(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      return option;
    }),
  );
  const validView = config.views.some(([value]) => value === preferredView)
    ? preferredView
    : config.views[0][0];
  viewSelect.value = validView;
  return validView;
}

/**
 * 切换评审角色并同步导航和用户信息。
 *
 * :param role: 目标角色标识。
 * :param preferredView: 可选的目标页面。
 * :param updateUrl: 是否同步浏览器查询参数。
 * :returns: None。
 */
function setRole(role, preferredView, updateUrl = true) {
  const config = roleConfig[role] || roleConfig.student;
  document.body.dataset.role = role;
  roleSelect.value = role;
  roleName.textContent = config.label;
  sidebarUser.textContent = config.user;
  sidebarAvatar.textContent = config.avatar;
  topUser.textContent = config.user;
  topAvatar.textContent = config.avatar;

  document.querySelectorAll(".nav-group[data-roles]").forEach((group) => {
    group.hidden = group.dataset.roles !== role;
    group.style.display = group.dataset.roles === role ? "" : "none";
  });

  const nextView = replaceViewOptions(role, preferredView);
  setView(nextView, updateUrl);
}

/**
 * 激活指定原型页面并同步导航状态。
 *
 * :param viewId: 目标页面 DOM 标识。
 * :param updateUrl: 是否同步浏览器查询参数。
 * :returns: None。
 */
function setView(viewId, updateUrl = true) {
  const target = document.getElementById(viewId);
  if (!target) return;
  document
    .querySelectorAll(".view")
    .forEach((view) => view.classList.toggle("is-active", view.id === viewId));
  document
    .querySelectorAll("[data-view]")
    .forEach((button) =>
      button.classList.toggle("is-active", button.dataset.view === viewId),
    );
  viewSelect.value = viewId;

  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("role", roleSelect.value);
    url.searchParams.set("view", viewId);
    history.replaceState(null, "", url);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

roleSelect.addEventListener("change", (event) => setRole(event.target.value));
viewSelect.addEventListener("change", (event) => setView(event.target.value));

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    const target = document.getElementById(view);
    if (!target) return;
    const role = target.dataset.role;
    if (role && role !== "all" && role !== roleSelect.value)
      setRole(role, view);
    else setView(view);
  });
});

reviewToggle.addEventListener("click", () => {
  const expanded = reviewToggle.getAttribute("aria-expanded") === "true";
  reviewToggle.setAttribute("aria-expanded", String(!expanded));
  reviewPanel.hidden = expanded;
  reviewToggle.querySelector("span").textContent = expanded ? "+" : "×";
});

document.querySelectorAll(".segmented, .workspace-tabs").forEach((group) => {
  group.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      group
        .querySelectorAll("button")
        .forEach((item) => item.classList.remove("is-active"));
      button.classList.add("is-active");
    });
  });
});

document.querySelectorAll(".js-reason").forEach((button) => {
  button.addEventListener("click", () => {
    const note = button.closest(".panel").querySelector(".reason-note");
    const opening = note.hidden;
    note.hidden = !opening;
    button.textContent = opening ? "收起推荐依据" : "为什么推荐给我？";
  });
});

const searchParams = new URLSearchParams(window.location.search);
const initialRole = roleConfig[searchParams.get("role")]
  ? searchParams.get("role")
  : "student";
setRole(initialRole, searchParams.get("view"), false);

if (window.matchMedia("(max-width: 560px)").matches) {
  reviewToggle.setAttribute("aria-expanded", "false");
  reviewPanel.hidden = true;
  reviewToggle.querySelector("span").textContent = "+";
}
