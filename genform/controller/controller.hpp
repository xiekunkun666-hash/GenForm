#pragma once

#include "genform/session.hpp"
#include <QPointer>
#include "genform/controller/ui_support.hpp"
#include <QVariant>
#include <QWindow>
#include <QTimer>

namespace genform::view { class Viewport; class SheetView; }
namespace genform::controller {

class SketchEditor;

#define GENFORM_PROPERTY(name) Q_PROPERTY(QVariant name READ name NOTIFY changed) public: QVariant name() const { return localizedProperty(QStringLiteral(#name),value(QStringLiteral(#name))); }
#define GENFORM_UNSUPPORTED(name) Q_INVOKABLE void name(QVariant first = {}, QVariant second = {}, QVariant third = {}) { Q_UNUSED(first); Q_UNUSED(second); Q_UNUSED(third); unsupported(QStringLiteral(#name)); }

class SimulationBridge : public QObject {
    Q_OBJECT
    GENFORM_PROPERTY(state)
    GENFORM_PROPERTY(mode)
    GENFORM_PROPERTY(assembly)
    GENFORM_PROPERTY(assemblyName)
    GENFORM_PROPERTY(components)
    GENFORM_PROPERTY(joints)
    GENFORM_PROPERTY(mates)
    GENFORM_PROPERTY(motion)
    GENFORM_PROPERTY(live)
    GENFORM_PROPERTY(params)
    GENFORM_PROPERTY(paramError)
    GENFORM_PROPERTY(picked)
    GENFORM_PROPERTY(pickedJoint)
    GENFORM_PROPERTY(isolatedName)
    GENFORM_PROPERTY(drag)
    GENFORM_PROPERTY(standardCatalog)
    Q_PROPERTY(QVariantMap static READ staticState NOTIFY changed)
public:
    explicit SimulationBridge(Session *session, QObject *parent = nullptr);
    QVariant value(const QString &key) const;
    QVariantMap staticState() const;
    Q_INVOKABLE void open(const QString &mode);
    Q_INVOKABLE void close();
    Q_INVOKABLE void setParam(const QString &key, const QVariant &value);
    Q_INVOKABLE void setForce(const QString &key, const QVariant &value);
    Q_INVOKABLE void setDrag(const QString &key, const QVariant &value);
    Q_INVOKABLE void runStatic();
    Q_INVOKABLE void runDrag();
    bool beginAssembly();
    bool dirty() const { return dirty_; }
    QString path() const { return path_; }
    QJsonObject displayModel() const { return display_; }
    QJsonObject measureSelection(const QJsonObject &selection);
    void undoAssembly();
    void redoAssembly();
    bool canUndo() const { return !undo_.isEmpty(); }
    bool canRedo() const { return !redo_.isEmpty(); }
    Q_INVOKABLE bool openAssembly(const QString &path);
    Q_INVOKABLE bool saveAssembly(const QString &path);
    Q_INVOKABLE void addParts(const QVariantList &paths);
    Q_INVOKABLE void addStandardPart(const QString &kind,const QString &series,const QString &size,const QString &length);
    Q_INVOKABLE void removePart(int index);
    Q_INVOKABLE void renamePart(int index,const QString &name);
    Q_INVOKABLE void selectPart(int index);
    Q_INVOKABLE void openPart(int index);
    Q_INVOKABLE QVariantList partMenu(int index) const;
    Q_INVOKABLE QVariantList partContext(int index) const;
    Q_INVOKABLE void partAction(int index,const QString &action);
    Q_INVOKABLE void mirrorPart(int index);
    Q_INVOKABLE void placePart(int index,const QString &field,int axis,const QVariant &value);
    Q_INVOKABLE void shiftPart(int index,int step);
    Q_INVOKABLE void addJoint(const QVariant &source={});
    Q_INVOKABLE void addMate(int part,int target,const QString &kind,const QString &axis);
    Q_INVOKABLE void deleteJoint(int index);
    Q_INVOKABLE void jointAction(int index,const QString &action);
    Q_INVOKABLE void jointCentre(int index);
    Q_INVOKABLE void selectJoint(int index);
    Q_INVOKABLE void setJoint(int index,double value);
    Q_INVOKABLE void setJointField(int index,const QString &field,const QVariant &value);
    Q_INVOKABLE void setMateField(int index,const QString &field,const QVariant &value);
    Q_INVOKABLE void playMotion();
    Q_INVOKABLE void scrubMotion(double seconds);
    Q_INVOKABLE void settleJoint();
    Q_INVOKABLE void runFasteners();
    Q_INVOKABLE void runInterference();
    Q_INVOKABLE void runSequence();
    Q_INVOKABLE void runStack(const QString &axis);
    GENFORM_UNSUPPORTED(alignThreads)
    Q_INVOKABLE void setQuality(const QString &quality);
    Q_INVOKABLE void takeFaces(const QString &role);
    Q_INVOKABLE void showFaces(const QString &role);
    Q_INVOKABLE void exitIsolation();
    Q_INVOKABLE void exportBill(const QString &path);
    bool exportAssembly(const QString &path);
    Q_INVOKABLE void pickJointParts(int index);
Q_SIGNALS:
    void changed();
    void notice(const QString &message);
    void modelChanged(const QJsonObject &model);
    void assemblyActivated();
    void openPartRequested(const QString &path);
    void editRequested(int index);
    void renameRequested(int index);
private:
    Session *session_;
    QString mode_, error_;
    QVariantMap parameters_, result_;
    QJsonObject assembly_,savedAssembly_,display_,pose_,resolvedParameters_;
    QJsonArray fixed_,loaded_;
    QString path_,quality_=QStringLiteral("medium");
    int picked_=-1,joint_=-1,pickingJoint_=-1;
    bool dirty_=false,timeline_=false;
    double seconds_=0;
    QTimer motionTimer_;
    QList<QJsonObject> undo_,redo_;
    QSet<int> hiddenParts_;
    QSet<int> beforeIsolation_;
    int isolatedPart_=-1;
    void unsupported(const QString &command);
    void run(const QString &mode);
    QJsonObject query(const QString &what,QJsonObject arguments={});
    bool commitAssembly(const QJsonObject &data,bool checkpoint=true,bool resetSelection=false);
    void setAssemblySelection(int part,int joint);
    void refreshAssembly();
    QVariantList componentRows() const;
    QVariantList jointRows() const;
    QVariantList resultRows() const;
};

class DrawingBridge;
class ManufactureUi;

class AppController : public QObject {
    Q_OBJECT
    GENFORM_PROPERTY(title)
    GENFORM_PROPERTY(docKind)
    GENFORM_PROPERTY(tree)
    GENFORM_PROPERTY(tab)
    GENFORM_PROPERTY(startPage)
    GENFORM_PROPERTY(busy)
    GENFORM_PROPERTY(canUndo)
    GENFORM_PROPERTY(canRedo)
    GENFORM_PROPERTY(form)
    GENFORM_PROPERTY(previewNote)
    GENFORM_PROPERTY(bodyText)
    GENFORM_PROPERTY(selectionText)
    Q_PROPERTY(QVariant hoverText READ hoverText NOTIFY hoverTextChanged)
public:
    QVariant hoverText() const { return localizedProperty(QStringLiteral("hoverText"),value(QStringLiteral("hoverText"))); }
    GENFORM_PROPERTY(progress)
    GENFORM_PROPERTY(sketchActive)
    GENFORM_PROPERTY(sketchTool)
    GENFORM_PROPERTY(sketchTitle)
    GENFORM_PROPERTY(sketchOperation)
    GENFORM_PROPERTY(sketchProps)
    GENFORM_PROPERTY(rapidSketch)
    GENFORM_PROPERTY(hint)
    GENFORM_PROPERTY(pickingPlane)
    GENFORM_PROPERTY(quickSnaps)
    GENFORM_PROPERTY(quickSnap)
    GENFORM_PROPERTY(snapToggles)
    GENFORM_PROPERTY(featureMenus)
    GENFORM_PROPERTY(viewState)
    GENFORM_PROPERTY(orientations)
    GENFORM_PROPERTY(displayStyles)
    GENFORM_PROPERTY(sceneNames)
    GENFORM_PROPERTY(showItems)
    GENFORM_PROPERTY(appearanceColors)
    GENFORM_PROPERTY(materialList)
    GENFORM_PROPERTY(isolatedName)
    GENFORM_PROPERTY(sceneContext)
    GENFORM_PROPERTY(sceneTarget)
    GENFORM_PROPERTY(returnAssembly)
    GENFORM_PROPERTY(layoutSketches)
    GENFORM_PROPERTY(recentFiles)
    GENFORM_PROPERTY(shortcuts)
    GENFORM_PROPERTY(actionTable)
    GENFORM_PROPERTY(actionGroups)
    GENFORM_PROPERTY(keyMap)
    GENFORM_PROPERTY(gestures)
    GENFORM_PROPERTY(gestureWheels)
    GENFORM_PROPERTY(settings)
    GENFORM_PROPERTY(settingsPath)
    GENFORM_PROPERTY(language)
    GENFORM_PROPERTY(languages)
    GENFORM_PROPERTY(designRules)
    GENFORM_PROPERTY(aiGuide)
    GENFORM_PROPERTY(measure)
    GENFORM_PROPERTY(measuring)
    GENFORM_PROPERTY(binding)
    GENFORM_PROPERTY(checkBusy)
    GENFORM_PROPERTY(checkCompleted)
    GENFORM_PROPERTY(checkCounts)
    GENFORM_PROPERTY(checkHighlight)
    GENFORM_PROPERTY(checkIssues)
    GENFORM_PROPERTY(checkOpen)
    GENFORM_PROPERTY(checkStale)
public:
    explicit AppController(Session *session, QObject *parent = nullptr);
    void attach(QWindow *window, view::Viewport *viewport, view::SheetView *sheet);
    QVariant value(const QString &key) const;
    Session *session() const { return session_; }
    SimulationBridge *simulation() const { return simulation_; }
    DrawingBridge *drawing() const { return drawing_; }
    void setApiPort(quint16 port) { apiPort_ = port; Q_EMIT changed(); }
    QJsonObject execute(const QString &command, const QJsonObject &arguments = {});
    QJsonObject viewCommand(const QString &command, const QJsonObject &arguments);
    QJsonObject smokeTest(view::Viewport *viewport);
    Q_INVOKABLE QString tr(const QString &text) const { return translated(text); }
    Q_INVOKABLE void setLanguage(const QString &code);
    Q_INVOKABLE void setSetting(const QString &key,const QVariant &value);
    void attachTheme(QObject *theme);
    Q_INVOKABLE void newOf(const QString &kind);
    Q_INVOKABLE void showStart();
    Q_INVOKABLE void openDocument(const QString &path);
    Q_INVOKABLE void openFiles(const QVariantList &paths);
    Q_INVOKABLE void dropFiles(const QVariantList &paths);
    Q_INVOKABLE void saveDocument(const QString &path);
    Q_INVOKABLE void exportModel(const QString &path);
    Q_INVOKABLE void forgetRecent(const QString &path);
    Q_INVOKABLE void runAction(const QString &identifier);
    Q_INVOKABLE void setTab(const QString &tab);
    Q_INVOKABLE void undo();
    Q_INVOKABLE void redo();
    Q_INVOKABLE void escape();
    Q_INVOKABLE void enterKey();
    Q_INVOKABLE void toggleMaximize();
    Q_INVOKABLE void minimizeWindow();
    Q_INVOKABLE void restoreWindow();
    Q_INVOKABLE void startCommand(const QString &command);
    Q_INVOKABLE void editFeature(const QString &identifier);
    Q_INVOKABLE void deleteFeature(const QString &identifier);
    Q_INVOKABLE void renameFeature(const QString &identifier, const QString &name);
    Q_INVOKABLE void toggleSuppress(const QString &identifier);
    Q_INVOKABLE void rollbackTo(int count);
    Q_INVOKABLE void selectFeature(const QString &identifier);
    Q_INVOKABLE void selectPlane(const QString &plane);
    Q_INVOKABLE void setField(const QString &key, const QVariant &value);
    Q_INVOKABLE void setFormFields(const QVariantMap &values);
    Q_INVOKABLE void focusField(const QString &key);
    Q_INVOKABLE void acceptForm();
    Q_INVOKABLE void cancelForm();
    Q_INVOKABLE QString featureName(const QString &identifier) const;
    Q_INVOKABLE QVariantList featureContext(const QString &identifier) const;
    Q_INVOKABLE QVariantList featureMenu(const QString &identifier) const;
    Q_INVOKABLE QVariantList treeMenu(const QString &kind, const QString &identifier) const;
    Q_INVOKABLE void contextAction(const QString &identifier, const QString &action);
    Q_INVOKABLE void treeAction(const QString &kind, const QString &identifier, const QString &action);
    Q_INVOKABLE void planeAction(const QString &plane, const QString &action);
    Q_INVOKABLE QVariantList planeChoices(const QString &identifier) const;
    Q_INVOKABLE void sketchPick(const QString &tool);
    Q_INVOKABLE void startSketch();
    Q_INVOKABLE void sketchOn(const QString &plane);
    Q_INVOKABLE void setSketchPlane(const QString &identifier, const QString &plane);
    Q_INVOKABLE void finishSketch();
    Q_INVOKABLE void cancelSketch();
    Q_INVOKABLE void useSketchTool(const QString &tool);
    Q_INVOKABLE void sketchAction(const QString &action);
    Q_INVOKABLE void toggleRapidSketch();
    Q_INVOKABLE void setQuickSnap(const QString &kind);
    Q_INVOKABLE void toggleSnap(const QString &kind);
    Q_INVOKABLE void viewAction(const QString &action);
    Q_INVOKABLE void setDisplayStyle(const QString &style);
    Q_INVOKABLE void setScene(const QString &scene);
    Q_INVOKABLE void toggleShow(const QString &kind);
    Q_INVOKABLE void toggleViewSetting(const QString &key);
    Q_INVOKABLE void setSection(const QString &plane, double offset);
    Q_INVOKABLE void setMaterial(const QString &name);
    Q_INVOKABLE void setAppearance(const QString &color);
    Q_INVOKABLE void setShortcut(const QString &identifier, const QString &key);
    Q_INVOKABLE void resetShortcut(const QString &identifier);
    Q_INVOKABLE void resetShortcuts();
    Q_INVOKABLE QString keyText(int key, int modifiers) const;
    Q_INVOKABLE void toggleMeasure();
    Q_INVOKABLE void runCheck();
    Q_INVOKABLE void clearCheck();
    Q_INVOKABLE void closeCheck();
    Q_INVOKABLE void toggleCheckLog();
    Q_INVOKABLE void toggleCheckHighlight();
    Q_INVOKABLE void focusIssue(int index);
    Q_INVOKABLE void backToPart();
    Q_INVOKABLE void backToAssembly();
    Q_INVOKABLE void bindProcesses();
    GENFORM_UNSUPPORTED(toggleExpand)
    GENFORM_UNSUPPORTED(selectSketchRelation)
    GENFORM_UNSUPPORTED(setGesture)
    GENFORM_UNSUPPORTED(resetGestures)
    Q_INVOKABLE void setRule(const QString &key, const QString &text);
    Q_INVOKABLE void resetRules();
Q_SIGNALS:
    void changed();
    void formChanged();
    void sketchChanged();
    void hoverTextChanged();
    void viewChanged();
    void settingsChanged();
    void kindChanged();
    void startChanged();
    void progressChanged();
    void measureChanged();
    void languageChanged();
    void treeAboutToChange();
    void treeChanged();
    void notice(const QString &message);
    void dialogRequested(const QString &which);
    void contextRequested(double x, double y);
    void viewMenuRequested(const QString &identifier, double x, double y);
    void appearanceRequested();
protected:
    bool eventFilter(QObject *watched, QEvent *event) override;
private:
    Session *session_;
    SimulationBridge *simulation_;
    DrawingBridge *drawing_;
    SketchEditor *editor_;
    QPointer<QWindow> window_;
    view::Viewport *viewport_ = nullptr;
    GuiSettings preferences_;
    UiTranslator translator_;
    QPointer<QObject> theme_;
    QString kind_ = QStringLiteral("part"), tab_ = QStringLiteral("feature"), hover_, plane_ = QStringLiteral("XY");
    QString sketchTool_ = QStringLiteral("select"), editingSketch_, previewNote_, quickSnap_;
    QJsonObject sketchParams_, form_, view_, progress_, previousCamera_;
    QJsonArray shapes_;
    QList<QJsonArray> sketchUndo_, sketchRedo_;
    QVariantMap keys_, defaultKeys_;
    QVariantList actions_;
    QSet<QString> hidden_;
    QSet<QString> snaps_{"end","mid","center","quad","int","near","hv","grid"};
    QList<QJsonObject> savedViews_;
    QStringList recent_;
    bool start_ = true, sketch_ = false, pickingPlane_ = false, rapid_ = false, gridSnap_ = true;
    bool measuring_ = false;
    mutable ManufactureUi *manufacture_ = nullptr;
    bool dark_=true,sketchTurned_=false,finishingCommand_=false;
    int selectedShape_ = -1;
    int formSerial_ = 0;
    quint16 apiPort_ = 0;
    QVariantMap measurement_;
    QVariantList treeRows() const;
    QVariantList toolRows() const;
    void refresh();
    void pushSketch();
    void receiveSketch(const QJsonArray &shapes);
    void selected(const QJsonObject &selection, bool additive);
    void unsupported(const QString &command);
    void remember(const QString &path);
    void makeForm(const QString &command, const QString &editing = {});
    QJsonObject featureForm() const;
    void createFeatureForm(const QString &command, const QString &editing);
    bool updateFeatureFormField(const QString &key, const QJsonValue &value);
    bool takeFeatureFormReference(const QStringList &kinds, const QJsonValue &value, const QString &label = {});
    bool takeFeatureFormSelection(const QJsonObject &selection, bool additive);
    void syncFeatureFormPick();
    void acceptFeatureForm();
    bool confirmDiscard();
    void measureSelection();
    void applyContext(const QString &action, const QString &identifier);
    void syncEditorUi();
    Q_SLOT void themeChanged();
    void savePreference(const QString &key,const QVariant &value);
    ManufactureUi *manufactureUi() const;
    void updateCheckHighlights();
};

#undef GENFORM_PROPERTY
#undef GENFORM_UNSUPPORTED

}
