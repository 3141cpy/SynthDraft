import "@testing-library/jest-dom/vitest";

// Radix UI 在 jsdom 中需要的 polyfill：pointer capture 与 scrollIntoView 在 jsdom
// 中未实现，会导致 Select / Dialog 等组件交互失败。
window.HTMLElement.prototype.scrollIntoView = () => {};
window.HTMLElement.prototype.hasPointerCapture = () => false;
window.HTMLElement.prototype.releasePointerCapture = () => {};
window.HTMLElement.prototype.setPointerCapture = () => {};
