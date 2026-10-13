// Theme.qml - 全局主题。
// 深色: 中性的深灰 (不是黑) 分三层 — 标题栏和状态栏最深, 工具栏和设计树浅一档, 卡片和菜单再浅一档;
// 三维视图是比面板略亮的灰色渐变。蓝色只作点缀: 工具栏图标、选中的行、当前页签和工具、主要按钮、回退线。
pragma Singleton
import QtQuick

QtObject {
    property bool darkMode: true

    readonly property color cBgTitle: darkMode ? "#25282D" : "#E6EBF2"         // 标题栏、状态栏
    readonly property color cBg: darkMode ? "#2F333A" : "#FFFFFF"              // 面板: 工具栏、设计树
    readonly property color cBgWorkspace: darkMode ? "#282B31" : "#F0F3F8"     // 面板上凹下去的地方 (页签槽)
    readonly property color cBgCard: darkMode ? "#3A3F47" : "#F4F7FB"          // 浮着的卡片、菜单
    readonly property color cBgHover: darkMode ? "#454B55" : "#E6ECF5"
    readonly property color cBgInput: darkMode ? "#24272C" : "#FFFFFF"
    readonly property color cDivider: darkMode ? "#444A54" : "#D8DFE9"
    readonly property color cText: darkMode ? "#ECEEF2" : "#1B222C"
    readonly property color cTextSec: darkMode ? "#B8BFC9" : "#4D5A6B"
    readonly property color cTextMuted: darkMode ? "#868E9A" : "#8492A4"
    readonly property color cAccent: darkMode ? "#5AA2FF" : "#2468F2"          // 点缀色: 蓝
    readonly property color cAccentStrong: darkMode ? "#3382F2" : "#1B56D6"    // 实心按钮的底 (白字压在上面要够深)
    readonly property color cAccentSoft: darkMode ? "#33486A" : "#E1ECFF"      // 选中行、当前工具的底
    readonly property color cAccentLine: darkMode ? "#4C76B8" : "#A9C6FA"      // 选中项的描边
    readonly property color cIcon: darkMode ? "#9CC4FF" : "#2F6FE8"            // 工具栏和菜单的图标: 淡一档的蓝
    readonly property color cError: darkMode ? "#F48A78" : "#D0402C"
    readonly property color cErrorSoft: darkMode ? "#4A2F2B" : "#FDECE9"
    readonly property color cAxisX: darkMode ? "#F0766A" : "#D8433A"
    readonly property color cAxisY: darkMode ? "#6BCB95" : "#2F9E62"
    readonly property color cAxisZ: cAccent

    // 悬停说明: 两种主题下都是深色的小卡片
    readonly property color cTipBg: darkMode ? "#191C21" : "#27303C"
    readonly property color cTipLine: darkMode ? "#4B5361" : "#3D4857"
    readonly property color cTipKey: darkMode ? "#2B3038" : "#39455A"
    readonly property color cTipText: "#F1F3F6"
    readonly property color cTipSub: "#B9C1CD"

    readonly property string font: "Microsoft YaHei UI"
    readonly property int textSize: 13
    readonly property int smallSize: 12
}
