#ifdef GENFORM_GUI_VIEWPORT_SELFTEST
#include "genform/controller/sketch_editor.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/viewport.hpp"
#include <QGuiApplication>
#include <QImage>
#include <QMouseEvent>
#include <QPainter>
#include <QQuickWindow>
#include <QTemporaryDir>
#include <QTextStream>
#include <cmath>
#include <stdexcept>

namespace {
void require(bool valid,const QString &message) { if (!valid) throw std::runtime_error(message.toUtf8().constData()); }
}
int main(int argc,char **argv) {
    QGuiApplication application(argc,argv); QQuickWindow window; window.resize(800,600);
    genform::controller::SketchEditor editor; genform::view::Viewport viewport(window.contentItem());
    viewport.setWidth(800); viewport.setHeight(600); viewport.setEditor(&editor); window.show(); application.processEvents();
    QStringList errors; int cases=0; QObject::connect(&editor,&genform::controller::SketchEditor::error,&editor,[&](const QString &error) { errors.append(error); });
    try {
        const auto reset=[&](const QString &plane=QStringLiteral("XY")) { viewport.endSketch(); editor.reset(); viewport.setSketch({},plane,7); viewport.setSnaps({}); errors.clear(); };
        const auto position=[&](double horizontal,double vertical,const QString &plane=QStringLiteral("XY")) {
            const auto coordinates=genform::domain::to_world({QVector2D(float(horizontal),float(vertical))},plane,7).first(); const auto state=viewport.cameraState(); const auto centre=state.value("centre").toArray();
            QMatrix4x4 rotation; rotation.rotate(float(state.value("pitch").toDouble()),1,0,0); rotation.rotate(float(state.value("yaw").toDouble()),0,0,1);
            const auto projected=rotation.map(coordinates-QVector3D(float(centre[0].toDouble()),float(centre[1].toDouble()),float(centre[2].toDouble())));
            return QPointF(viewport.width()/2+state.value("pan_x").toDouble()+projected.x()*state.value("scale").toDouble(),viewport.height()/2+state.value("pan_y").toDouble()-projected.y()*state.value("scale").toDouble());
        };
        const auto event=[&](QEvent::Type type,const QPointF &point,Qt::MouseButton button,Qt::MouseButtons buttons) { QMouseEvent mouse(type,point,point,button,buttons,Qt::NoModifier); QCoreApplication::sendEvent(&viewport,&mouse); };
        const auto click=[&](double horizontal,double vertical,const QString &plane=QStringLiteral("XY")) { const auto point=position(horizontal,vertical,plane); event(QEvent::MouseButtonPress,point,Qt::LeftButton,Qt::LeftButton); event(QEvent::MouseButtonRelease,point,Qt::LeftButton,Qt::NoButton); };
        for (const auto &plane : {QString("XY"),QString("XZ"),QString("YZ")}) {
            reset(plane); editor.setTool("rect"); click(-20,-10,plane); click(20,10,plane);
            require(errors.isEmpty() && editor.shapes().size()==1,plane+" rectangle mouse events"); const auto rectangle=editor.shapes()[0].toObject();
            require(std::abs(rectangle.value("w").toDouble()-40)<1e-4 && std::abs(rectangle.value("h").toDouble()-20)<1e-4,plane+" local coordinates"); ++cases;
            editor.setTool("select"); const auto before=editor.shapes(); click(-20,-10,plane); require(editor.shapes()==before,plane+" selection must not drift geometry"); ++cases;
        }
        reset(); editor.setTool("circle3"); click(10,0); click(0,10); click(-10,0); require(editor.shapes().size()==1 && std::abs(editor.shapes()[0].toObject().value("r").toDouble()-10)<1e-4,"three point circle mouse events"); ++cases;
        reset(); editor.setTool("ellipse"); click(0,0); click(20,0); click(20,5); require(editor.shapes().size()==1 && std::abs(editor.shapes()[0].toObject().value("ry").toDouble()-5)<1e-4,"ellipse mouse events"); ++cases;
        reset(); editor.setTool("arc"); click(0,0); click(10,0); click(0,-10); require(editor.shapes().size()==1 && std::abs(editor.shapes()[0].toObject().value("a0").toDouble()+90)<1e-4,"clockwise arc mouse events"); ++cases;
        reset(); editor.setTool("slot"); click(0,0); click(20,0); click(20,3); require(editor.shapes().size()==1 && std::abs(editor.shapes()[0].toObject().value("w").toDouble()-6)<1e-4,"slot mouse events"); ++cases;
        reset(); editor.setTool("rect"); click(-20,-10); click(20,10); editor.setTool("select");
        const auto first=position(-20,-10),last=position(-15,-7); event(QEvent::MouseButtonPress,first,Qt::LeftButton,Qt::LeftButton); event(QEvent::MouseMove,last,Qt::NoButton,Qt::LeftButton); event(QEvent::MouseButtonRelease,last,Qt::LeftButton,Qt::NoButton);
        require(std::abs(editor.shapes()[0].toObject().value("cx").toDouble()-5)<1e-4 && std::abs(editor.shapes()[0].toObject().value("cy").toDouble()-3)<1e-4,"drag commits native edit"); ++cases;
        int consumed=0; QObject::connect(&viewport,&genform::view::Viewport::quickSnapConsumed,&viewport,[&] { ++consumed; }); viewport.setSnaps({},"center"); editor.setTool("point"); click(5.1,3.1);
        require(consumed==1 && editor.shapes().size()==2 && std::abs(editor.shapes()[1].toObject().value("x").toDouble()-5)<1e-4,"one shot centre snapping"); click(8.3,7.1); require(consumed==1 && std::abs(editor.shapes()[2].toObject().value("x").toDouble()-8.3)<1e-4,"one shot does not persist"); cases+=2;
        for (const auto &plane : {QString("XY"),QString("XZ"),QString("YZ")}) {
            viewport.endSketch(); editor.reset(); viewport.setView("iso"); const auto camera=viewport.cameraState(); viewport.setSketch({},plane,7,false); viewport.setSnaps({}); editor.setTool("rect");
            require(viewport.cameraState()==camera,plane+" rapid mode keeps camera"); click(-20,-10,plane); click(20,10,plane); require(editor.shapes().size()==1,plane+" rapid oblique mouse rectangle"); const auto shape=editor.shapes()[0].toObject(); require(std::abs(shape.value("w").toDouble()-40)<0.02 && std::abs(shape.value("h").toDouble()-20)<0.02 && std::abs(shape.value("cx").toDouble())<0.02 && std::abs(shape.value("cy").toDouble())<0.02,plane+" rapid ray-plane coordinates"); ++cases;
        }
        QTemporaryDir temporary; require(temporary.isValid() && viewport.saveImage(temporary.filePath("sketch.png")),"software viewport image export"); const QImage image(temporary.filePath("sketch.png")); require(!image.isNull() && image.width()==800 && image.height()==600,"software viewport image dimensions"); ++cases;
        require(errors.isEmpty(),errors.join("; ")); QTextStream(stdout)<<"GUI_VIEWPORT_SELFTEST_OK cases="<<cases<<Qt::endl; return 0;
    } catch (const std::exception &error) { QTextStream(stderr)<<"GUI_VIEWPORT_SELFTEST_FAILED "<<error.what()<<" errors="<<errors.join("; ")<<Qt::endl; return 1; }
}
#endif
