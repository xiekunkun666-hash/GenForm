// Theme.qml - 全局主题。
// 深色只用三种颜色: 黑 (几档深浅分出层次, 不是纯黑, 看久了不累)、白 (文字和图标, 次要的淡一些)、蓝 (只给选中、当前工具、主要按钮 —
// 是一档偏浅的天蓝, 面积小)。大致的比例: 黑是底, 白是内容, 蓝只是点一下。
// 例外只有两处约定俗成的: 出错标红; 坐标轴 X 红 / Y 绿 / Z 蓝。
pragma Singleton
import QtQuick

QtObject {
    property bool darkMode: true

    readonly property color cBgTitle: darkMode ? "#141517" : "#E6EBF2"         // 标题栏、状态栏
    readonly property color cBg: darkMode ? "#1C1D20" : "#FFFFFF"              // 面板: 工具栏、设计树
    readonly property color cBgWorkspace: darkMode ? "#141517" : "#F0F3F8"     // 面板上凹下去的地方 (页签槽)
    readonly property color cBgCard: darkMode ? "#25262A" : "#F4F7FB"          // 浮着的卡片、菜单
    readonly property color cBgHover: darkMode ? "#313338" : "#E6ECF5"
    readonly property color cBgInput: darkMode ? "#131416" : "#FFFFFF"
    readonly property color cDivider: darkMode ? "#34363B" : "#D8DFE9"
    readonly property color cText: darkMode ? "#F1F2F4" : "#1B222C"
    readonly property color cTextSec: darkMode ? "#BBBEC4" : "#4D5A6B"
    readonly property color cTextMuted: darkMode ? "#80848B" : "#8492A4"
    readonly property color cAccent: darkMode ? "#7DB4FF" : "#2468F2"          // 点缀色: 蓝
    readonly property color cAccentStrong: darkMode ? "#4C8FEF" : "#1B56D6"    // 实心按钮的底 (白字压在上面要够深)
    readonly property color cAccentSoft: darkMode ? "#26364D" : "#E1ECFF"      // 选中行、当前工具的底
    readonly property color cAccentLine: darkMode ? "#4A76B8" : "#A9C6FA"      // 选中项的描边
    readonly property color cIcon: darkMode ? "#DADDE2" : "#2F6FE8"            // 工具栏和菜单的图标: 深色下是白的 (蓝只留给选中的)
    readonly property color cError: darkMode ? "#F48A78" : "#D0402C"
    readonly property color cErrorSoft: darkMode ? "#4A2F2B" : "#FDECE9"
    readonly property color cAxisX: darkMode ? "#F0766A" : "#D8433A"
    readonly property color cAxisY: darkMode ? "#6BCB95" : "#2F9E62"
    readonly property color cAxisZ: cAccent
    // 设计树的层级色: 一层一种颜色, 像代码编辑器里一对对括号按嵌套层数换色 (VS Code 的配色: 金 → 紫 → 蓝, 再往下青、橙, 然后轮回)
    readonly property var levelColors: darkMode ? ["#FFD700", "#DA70D6", "#179FFF", "#4EC9B0", "#F48771"]
                                                : ["#B58900", "#A626A4", "#0B6BCB", "#1F8F6E", "#C2410C"]
    function levelColor(level) { return levelColors[((level % levelColors.length) + levelColors.length) % levelColors.length] }
    readonly property color cGood: darkMode ? cAccent : "#3FB97F"          // "完成 / 正常": 深色下也是蓝
    readonly property color cBad: darkMode ? "#FFFFFF" : "#E5484D"         // "放弃": 深色下是白

    // 悬停说明: 两种主题下都是深色的小卡片
    readonly property color cTipBg: darkMode ? "#000000" : "#27303C"
    readonly property color cTipLine: darkMode ? "#3A3A3E" : "#3D4857"
    readonly property color cTipKey: darkMode ? "#1C1C1E" : "#39455A"
    readonly property color cTipText: "#FFFFFF"
    readonly property color cTipSub: darkMode ? "#C6C6C8" : "#B9C1CD"

    readonly property string font: "Microsoft YaHei UI"
    readonly property int textSize: 13
    readonly property int smallSize: 12
}
