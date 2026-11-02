#ifdef GENFORM_GUI_SELFTEST
#include "genform/controller/sketch_editor.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/sketch_snap.hpp"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QTextStream>
#include <cmath>
#include <stdexcept>

namespace {
void require(bool condition,const QString &message) { if (!condition) throw std::runtime_error(message.toUtf8().constData()); }
bool close(double first,double second) { return std::abs(first-second)<1e-4; }
QJsonObject line(double firstX,double firstY,double secondX,double secondY) {
    return {{"type","line"},{"x1",firstX},{"y1",firstY},{"x2",secondX},{"y2",secondY}};
}
}
int main(int argc,char **argv) {
    QCoreApplication application(argc,argv);
    using genform::controller::SketchEditor;
    SketchEditor editor; QStringList errors; int cases=0;
    QObject::connect(&editor,&SketchEditor::error,&editor,[&errors](const QString &error) { errors.append(error); });
    try {
        const auto draw=[&](const QString &tool,const QVector<QVector2D> &points,const QString &type,bool finish=false) {
            editor.reset(); errors.clear(); require(editor.setTool(tool),tool+" tool rejected");
            for (const auto &point : points) editor.press(point,0.1);
            if (finish) editor.finishDraft();
            require(errors.isEmpty(),tool+": "+errors.join("; "));
            require(editor.shapes().size()==1 && editor.shapes()[0].toObject().value("type")==type,tool+" produced wrong shape");
            if (type!="text" && type!="point") require(genform::domain::length(editor.shapes()[0].toObject())>0,tool+" empty geometry");
            ++cases;
        };
        draw("line",{{0,0},{20,10}},"line");
        draw("centerline",{{0,0},{20,10}},"line"); require(editor.shapes()[0].toObject().value("construction").toBool(),"centerline flag");
        draw("midline",{{0,0},{20,10}},"line"); require(close(editor.shapes()[0].toObject().value("x1").toDouble(),-20),"midline origin");
        draw("rect",{{0,0},{20,10}},"rect");
        draw("crect",{{0,0},{20,10}},"rect"); require(close(editor.shapes()[0].toObject().value("w").toDouble(),40),"centered rectangle width");
        draw("rect3",{{0,0},{20,10},{15,20}},"polygon");
        draw("crect3",{{0,0},{20,10},{15,20}},"polygon");
        draw("pgram",{{0,0},{20,10},{30,30}},"polygon");
        draw("circle",{{0,0},{10,0}},"circle");
        draw("circle3",{{10,0},{0,10},{-10,0}},"circle");
        draw("arc",{{0,0},{10,0},{0,10}},"arc");
        draw("arc",{{0,0},{10,0},{0,-10}},"arc"); require(close(editor.shapes()[0].toObject().value("a0").toDouble(),-90) && close(editor.shapes()[0].toObject().value("a1").toDouble(),0),"clockwise arc sweep");
        draw("arc3",{{10,0},{-10,0},{0,10}},"arc");
        draw("slot",{{0,0},{20,0},{20,3}},"slot");
        draw("cslot",{{0,0},{20,0},{20,3}},"slot");
        draw("aslot3",{{10,0},{-10,0},{0,10},{0,12}},"arcslot");
        draw("caslot",{{0,0},{10,0},{0,10},{0,12}},"arcslot");
        draw("ngon",{{0,0},{10,0}},"ngon");
        draw("polygon",{{0,0},{10,0},{10,10}},"polygon",true);
        draw("ellipse",{{0,0},{20,0},{20,5}},"ellipse");
        draw("spline",{{0,0},{10,5},{20,0}},"spline",true);
        draw("sspline",{{0,0},{10,5},{20,0}},"spline",true);
        draw("equation",{{0,0}},"equation");
        draw("point",{{4,5}},"point"); require(editor.hit({4,5},0.1)==0,"point picking");
        draw("text",{{4,5}},"text"); require(editor.hit({4,5},0.1)==0,"text picking");

        editor.reset({line(0,0,10,5),line(0,15,10,20)}); editor.setSelection({0,1}); editor.action("rel:horizontal");
        require(close(editor.shapes()[0].toObject().value("y1").toDouble(),editor.shapes()[0].toObject().value("y2").toDouble()),"horizontal relation"); ++cases;
        editor.beginOperation("pattern"); editor.setField("nx",3); editor.setField("ny",2); editor.acceptOperation();
        require(editor.shapes().size()==12,"linear pattern count"); ++cases;
        editor.reset({line(10,0,20,0)}); editor.setSelection({0}); editor.beginOperation("cpattern"); editor.setField("count",4); editor.acceptOperation();
        require(editor.shapes().size()==4,"circular pattern count"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.setSelection({0}); editor.setTool("move"); editor.press({0,0},0.1); editor.press({5,6},0.1);
        require(close(editor.shapes()[0].toObject().value("x1").toDouble(),5),"move"); ++cases;
        editor.setSelection({0}); editor.setTool("mirror"); editor.press({0,0},0.1); editor.press({0,10},0.1);
        require(editor.shapes().size()==2 && close(editor.shapes()[1].toObject().value("x1").toDouble(),-5),"mirror"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.setSelection({0}); editor.beginOperation("rotate"); editor.setField("angle",90); editor.acceptOperation();
        require(close(editor.shapes()[0].toObject().value("y2").toDouble(),10),"rotate"); ++cases;
        editor.beginOperation("scale"); editor.setField("factor",2); editor.acceptOperation();
        require(close(editor.shapes()[0].toObject().value("y2").toDouble(),20),"scale"); ++cases;
        editor.reset({line(0,0,20,0),line(10,-10,10,10)}); editor.setTool("trim"); editor.press({5,0},0.1);
        require(editor.shapes().size()==2 && close(genform::domain::length(editor.shapes()[0].toObject()),10),"trim"); ++cases;
        editor.reset({line(0,0,5,0),line(10,-10,10,10)}); editor.setTool("extend"); editor.press({4,0},0.1);
        require(close(genform::domain::length(editor.shapes()[0].toObject()),10),"extend"); ++cases;
        editor.reset({line(0,0,20,0),line(20,0,20,20)}); editor.setTool("fillet"); editor.press({20,0},0.1);
        require(editor.shapes().size()==3 && editor.shapes()[2].toObject().value("type")=="arc","fillet"); ++cases;
        editor.reset({QJsonObject{{"type","circle"},{"cx",0},{"cy",0},{"r",10}}}); editor.setTool("offset"); editor.press({10,0},0.1); editor.press({12,0},0.1);
        require(editor.shapes().size()==2 && close(editor.shapes()[1].toObject().value("r").toDouble(),12),"offset"); ++cases;
        editor.reset(); editor.setReferences({line(0,0,10,0)}); editor.setTool("convert"); editor.press({5,0},0.1);
        require(editor.shapes().size()==1,"convert reference"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.press({5,0},0.1); editor.move({10,4}); editor.release({10,4});
        require(close(editor.shapes()[0].toObject().value("x1").toDouble(),5) && close(editor.shapes()[0].toObject().value("y1").toDouble(),4),"drag"); ++cases;
        editor.reset({QJsonObject{{"type","point"},{"x",100},{"y",100}},line(0,0,5,5)}); editor.box({-1,-1},{6,6},false,false);
        require(editor.selection()==QVector<int>{1},"box point isolation"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.setSelection({0}); editor.beginOperation("dimension"); editor.setField("value",25); editor.acceptOperation();
        require(close(genform::domain::length(editor.shapes()[0].toObject()),25),"dimension"); ++cases;
        editor.reset({line(0,0,10,0),QJsonObject{{"type","text"},{"x",0},{"y",0},{"text","CAD"},{"height",2}}}); editor.setSelection({0,1}); editor.action("textpath");
        require(editor.shapes()[1].toObject().value("path").isObject(),"text path"); ++cases;
        editor.setSelection({1}); editor.beginOperation("scale"); editor.setField("factor",2); editor.acceptOperation();
        require(close(editor.shapes()[1].toObject().value("height").toDouble(),4) && close(editor.shapes()[1].toObject().value("path").toObject().value("x2").toDouble(),20),"scale text and path"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.press({5,0},0.1); editor.move({7,3}); editor.escape();
        require(close(editor.shapes()[0].toObject().value("x1").toDouble(),0),"escape rolls back drag"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.setTool("text"); editor.setField("opt_text","Edited"); editor.press({2,3},0.1); editor.setField("opt_text","Next"); editor.press({4,5},0.1);
        require(editor.shapes()[1].toObject().value("text")=="Edited" && editor.shapes()[2].toObject().value("text")=="Next","tool options do not mutate selected shape"); ++cases;
        editor.reset({line(0,0,50,0)}); editor.setSelection({0}); editor.setTool("text"); editor.press({0,0},0.1);
        require(editor.shapes()[1].toObject().value("path").toObject().value("type")=="line","selected curve becomes text path"); ++cases;
        editor.reset({line(0,0,10,0)}); editor.setSelection({0}); editor.beginOperation("pattern"); editor.setField("nx",2); require(editor.preview().size()==1,"pattern preview"); editor.setField("nx",1.5); errors.clear(); editor.acceptOperation();
        require(editor.shapes().size()==1 && !errors.isEmpty(),"fractional pattern rejects"); ++cases;
        editor.reset({line(0,0,10,0),line(0,0,10,0)}); editor.beginOperation("repair"); editor.acceptOperation(); require(editor.shapes().size()==1,"repair duplicates"); ++cases;
        editor.reset({line(0,0,10,0),line(0,10,10,20)}); editor.setSelection({0,1}); editor.action("rel:parallel");
        require(close(editor.shapes()[1].toObject().value("y1").toDouble(),editor.shapes()[1].toObject().value("y2").toDouble()),"parallel relation"); ++cases;
        editor.reset({QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",10}}}); editor.setSelection({0}); editor.action("explode"); require(editor.shapes().size()==4,"explode contour"); ++cases;
        errors.clear(); editor.action("not-supported"); require(!errors.isEmpty(),"unsupported action must report error"); ++cases;
        editor.reset(); errors.clear(); editor.setTool("rect"); editor.press({0,0},0.1); editor.press({0,10},0.1);
        require(editor.shapes().isEmpty() && !errors.isEmpty(),"degenerate rectangle must be rejected"); ++cases;
        const QJsonArray snapLines{line(10,10,30,10),line(20,0,20,20)};
        const auto snap=[&](const QVector2D &point,const QSet<QString> &enabled,const QString &only=QString()) { return genform::view::snapSketch(snapLines,point,10,enabled,only); };
        auto landed=snap({10.2f,10.1f},{"end"}); require(landed.kind=="end" && close(landed.point.x(),10),"endpoint snap"); ++cases;
        landed=snap({19.9f,10.2f},{"mid"}); require(landed.kind=="mid" && close(landed.point.x(),20),"midpoint snap"); ++cases;
        landed=snap({19.9f,10.2f},{"int"}); require(landed.kind=="int" && close(landed.point.y(),10),"intersection snap"); ++cases;
        landed=snap({13.3f,10.2f},{"near"}); require(landed.kind=="near" && close(landed.point.y(),10),"nearest curve snap"); ++cases;
        landed=snap({13.3f,15.2f},{"grid"}); require(landed.kind=="grid" && close(landed.point.x(),13) && close(landed.point.y(),15),"grid snap"); ++cases;
        landed=snap({10.2f,15.2f},{"hv"}); require(landed.kind=="hv" && close(landed.point.x(),10),"horizontal vertical alignment"); ++cases;
        landed=snap({13.3f,15.2f},{}); require(landed.kind.isEmpty() && close(landed.point.x(),13.3),"disabled snap retains position"); ++cases;
        landed=snap({11.9f,11.1f},{"grid"},"end"); require(landed.kind=="end" && close(landed.point.x(),10),"quick snap widened exclusive reach"); ++cases;
        const QJsonArray circle{QJsonObject{{"type","circle"},{"cx",0},{"cy",0},{"r",10}}};
        landed=genform::view::snapSketch(circle,{0.1f,0.2f},10,{"center"}); require(landed.kind=="center" && close(landed.point.y(),0),"circle centre snap"); ++cases;
        landed=genform::view::snapSketch(circle,{10.1f,0.2f},10,{"quad"}); require(landed.kind=="quad" && close(landed.point.x(),10),"circle quadrant snap"); ++cases;
        landed=genform::view::snapSketch({snapLines[0]},{10.2f,10.1f},10,{"end"},{},{0}); require(landed.kind.isEmpty(),"drag excludes moving geometry"); ++cases;
        landed=genform::view::snapSketch({},{4.1f,4.2f},10,{"end"},{},{},{{4,4},{8,8},{9,10}}); require(landed.kind=="end" && close(landed.point.x(),4),"draft closure snap"); ++cases;
        QTextStream(stdout)<<"GUI_SKETCH_SELFTEST_OK cases="<<cases<<Qt::endl;
        return 0;
    } catch (const std::exception &error) {
        QTextStream(stderr)<<"GUI_SKETCH_SELFTEST_FAILED "<<error.what()<<" errors="<<errors.join("; ")<<Qt::endl;
        return 1;
    }
}
#endif
