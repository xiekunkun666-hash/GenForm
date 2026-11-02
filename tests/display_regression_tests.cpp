#include "genform/controller/controller.hpp"
#include "genform/domain/geometry.hpp"
#include "genform/view/sheet.hpp"
#include "genform/view/viewport.hpp"
#include <QApplication>
#include <QFile>
#include <QImage>
#include <QJsonDocument>
#include <QLineF>
#include <QMap>
#include <QMatrix4x4>
#include <QPainter>
#include <QQuickWindow>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QTest>
#include <QTextStream>
#include <algorithm>
#include <cmath>
#include <functional>
#include <memory>
#include <stdexcept>

#if defined(_MSC_VER) && !defined(_CPPUNWIND)
#error display_regression_tests requires /EHsc for assertion and QSignalSpy cleanup
#endif

namespace {
using genform::controller::AppController;
using genform::view::Viewport;

void require(bool valid,const QString &message) {
    if (!valid) throw std::runtime_error(message.toUtf8().constData());
}

QByteArray jsonBytes(const QJsonObject &object) { return QJsonDocument(object).toJson(QJsonDocument::Compact); }

QByteArray fileBytes(const QString &path) {
    QFile file(path);
    require(file.open(QIODevice::ReadOnly),"Cannot read isolated fixture: "+file.errorString());
    return file.readAll();
}

QVector3D vectorOf(const QJsonValue &value) {
    const auto coordinates=value.toArray();
    require(coordinates.size()==3,"Kernel geometry must expose three-dimensional coordinates");
    return {float(coordinates[0].toDouble()),float(coordinates[1].toDouble()),float(coordinates[2].toDouble())};
}

QJsonObject topology(const QJsonArray &table,int identifier) {
    for (const auto &entry : table) if (entry.toObject().value("id").toInt(-1)==identifier) return entry.toObject();
    throw std::runtime_error("Picked topology must exist in the real kernel table");
}

QPointF project(const Viewport &viewport,const QVector3D &point) {
    const auto camera=viewport.cameraState();
    QMatrix4x4 rotation;
    rotation.rotate(float(camera.value("pitch").toDouble()),1,0,0);
    rotation.rotate(float(camera.value("yaw").toDouble()),0,0,1);
    const auto turned=rotation.map(point-vectorOf(camera.value("centre")));
    return {viewport.width()/2+camera.value("pan_x").toDouble()+turned.x()*camera.value("scale").toDouble(),
        viewport.height()/2+camera.value("pan_y").toDouble()-turned.y()*camera.value("scale").toDouble()};
}

struct PersistentState {
    QByteArray model,document,saved;
    QString path;
    quint64 revision;
    bool dirty,undo,redo;

    explicit PersistentState(const genform::Session &session)
        : model(jsonBytes(session.model)),document(jsonBytes(session.document.toData())),
          saved(fileBytes(session.document.path)),path(session.document.path),revision(session.document.revision),
          dirty(session.document.dirty),undo(session.document.canUndo()),redo(session.document.canRedo()) {}

    void requireGeometry(const genform::Session &session) const {
        require(jsonBytes(session.model)==model,"Display operation must not rewrite kernel/model JSON");
        require(session.document.revision==revision,"Display operation must not rebuild or revise geometry");
        require(session.document.path==path && fileBytes(path)==saved,"Display operation must not rewrite the saved fixture");
        require(session.document.canUndo()==undo && session.document.canRedo()==redo,"Display operation must preserve geometry undo/redo state");
    }

    void requireUnchanged(const genform::Session &session) const {
        requireGeometry(session);
        require(jsonBytes(session.document.toData())==document,"Rendering and selection must not change document JSON");
        require(session.document.dirty==dirty,"Rendering and selection must preserve document dirty state");
    }
};

QImage render(Viewport &viewport,const QColor &background=Qt::transparent) {
    QImage image(QSize(qRound(viewport.width()),qRound(viewport.height())),QImage::Format_ARGB32_Premultiplied);
    image.fill(background);
    QPainter painter(&image);
    viewport.paint(&painter);
    painter.end();
    return image;
}

int pixels(const QImage &image,const std::function<bool(const QColor &)> &accepts) {
    int count=0;
    for (int row=0;row<image.height();++row) for (int column=0;column<image.width();++column)
        if (accepts(image.pixelColor(column,row))) ++count;
    return count;
}

bool blue(const QColor &color) {
    return color.alpha()>180 && color.blue()>color.red()*1.8 && color.blue()>color.green()*1.3;
}

bool red(const QColor &color) {
    return color.alpha()>180 && color.red()>color.green()*1.7 && color.red()>color.blue()*1.6;
}

bool orange(const QColor &color) {
    return color.alpha()>180 && color.red()>220 && color.green()>130 && color.blue()<130;
}

void requireShade(const QColor &actual,const QColor &base,const QString &message) {
    const double factor=double(std::max({actual.red(),actual.green(),actual.blue()}))/std::max({base.red(),base.green(),base.blue()});
    require(actual.alpha()==255 && factor>0.35 && factor<1.05 && std::abs(actual.red()-base.red()*factor)<4
        && std::abs(actual.green()-base.green()*factor)<4 && std::abs(actual.blue()-base.blue()*factor)<4,
        message+QString("; actual=%1 alpha=%2 base=%3").arg(actual.name()).arg(actual.alpha()).arg(base.name()));
}

QJsonObject materialWithColor(const QString &color) {
    for (const auto &entry : genform::domain::material_catalog())
        if (entry.toObject().value("color").toString().compare(color,Qt::CaseInsensitive)==0) return entry.toObject();
    throw std::runtime_error("Expected fixture material must exist in the production catalog");
}

struct Fixture {
    QTemporaryDir temporary;
    genform::Session session;
    QQuickWindow window;
    Viewport viewport;
    genform::view::SheetView sheet;
    std::unique_ptr<AppController> controller;
    QString body,boss;

    explicit Fixture(bool secondFeature=false) : viewport(window.contentItem()),sheet(window.contentItem()) {
        require(temporary.isValid(),"Display fixture needs isolated settings and document storage");
        qputenv("GENFORM_SETTINGS",temporary.filePath("settings.json").toUtf8());
        require(genform::kernel::Kernel::available(),"Display regressions require the real OpenCascade kernel");
        window.resize(900,700);
        viewport.setSize(QSizeF(900,700));
        sheet.setVisible(false);
        controller=std::make_unique<AppController>(&session);
        controller->newOf("part");
        controller->attach(&window,&viewport,&sheet);
        const auto sketch=command("sketch",{{"plane","XY"},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",20},{"h",20}}}}}).value("id").toString();
        body=command("extrude",{{"sketch",sketch},{"distance",20}}).value("id").toString();
        controller->contextAction(sketch,"hide");
        if (secondFeature) {
            const auto bossSketch=command("sketch",{{"plane","XY"},{"offset",20},{"shapes",QJsonArray{QJsonObject{{"type","rect"},{"cx",0},{"cy",0},{"w",8},{"h",8}}}}}).value("id").toString();
            boss=command("extrude",{{"sketch",bossSketch},{"distance",6}}).value("id").toString();
            controller->contextAction(bossSketch,"hide");
        }
        require(!body.isEmpty() && session.model.value("has_body").toBool(),"Fixture must build a real extruded box");
        require(session.model.value("tris").toArray().size()>=12 && session.model.value("faces").toArray().size()>=6
            && session.model.value("edges").toArray().size()>=12,"Fixture must expose native face/edge topology and triangles");
        require(session.model.value("tris").toArray().size()==session.model.value("tri_face").toArray().size()
            && session.model.value("segments").toArray().size()==session.model.value("segment_edge").toArray().size(),"Kernel triangles and edge segments must retain topology attribution");
        controller->setAppearance("#b78d58");
        controller->setDisplayStyle("shaded_edges");
        viewport.setPlanesVisible(false);
        viewport.setDark(false);
        viewport.restoreCamera({{"yaw",-45},{"pitch",-54.736},{"scale",12},{"pan_x",0},{"pan_y",0},{"centre",QJsonArray{0,0,secondFeature?13:10}}});
        session.document.save(temporary.filePath("display-fixture.gform"));
        window.show();
        QCoreApplication::processEvents();
        QTest::qWait(20);
        render(viewport);
    }

    QJsonObject command(const QString &name,const QJsonObject &arguments={}) {
        const auto reply=controller->execute(name,arguments);
        require(reply.value("ok").toBool(),name+" failed: "+QString::fromUtf8(jsonBytes(reply)));
        return reply;
    }

    QImage image(const QColor &background=Qt::transparent) {
        const PersistentState before(session);
        const auto selection=session.selection;
        const auto result=render(viewport,background);
        before.requireUnchanged(session);
        require(session.selection==selection,"Painting must not change live selection");
        return result;
    }

    QColor sample(const QImage &image,const QVector3D &point) const {
        const auto pixel=project(viewport,point).toPoint();
        require(image.rect().adjusted(4,4,-4,-4).contains(pixel),"Geometry sample must be safely inside the actual viewport image");
        return image.pixelColor(pixel);
    }

    QJsonObject click(const QVector3D &point) {
        image();
        const auto pixel=viewport.mapToScene(project(viewport,point)).toPoint();
        require(QRect(QPoint(0,0),window.size()).adjusted(8,8,-8,-8).contains(pixel),"Real pick must lie inside the offscreen window");
        QSignalSpy picked(&viewport,&Viewport::picked);
        require(picked.isValid(),"QtTest must observe the production Viewport::picked signal");
        QTest::mouseClick(&window,Qt::LeftButton,Qt::NoModifier,pixel);
        QCoreApplication::processEvents();
        require(picked.count()==1,"A real mouse click must emit exactly one production pick");
        const auto selection=picked.first()[0].value<QJsonObject>();
        require(session.selection==selection,"Attached AppController must consume the real viewport pick");
        return selection;
    }

    QVector3D topFaceInterior() const {
        const auto vertices=session.model.value("verts").toArray(),triangles=session.model.value("tris").toArray();
        const auto faces=session.model.value("faces").toArray(),numbers=session.model.value("tri_face").toArray();
        double bestClearance=0;
        QVector3D best;
        for (int index=0;index<triangles.size();++index) {
            const auto face=topology(faces,numbers[index].toInt(-1));
            if (face.value("feature")!=body || std::abs(vectorOf(face.value("center")).z()-20)>0.001) continue;
            const auto indices=triangles[index].toArray();
            require(indices.size()==3,"Real top face must expose triangle indices");
            const auto first=vectorOf(vertices[indices[0].toInt()]),second=vectorOf(vertices[indices[1].toInt()]),third=vectorOf(vertices[indices[2].toInt()]);
            for (int firstWeight=1;firstWeight<6;++firstWeight) for (int secondWeight=1;secondWeight<7-firstWeight;++secondWeight) {
                const auto point=(first*float(firstWeight)+second*float(secondWeight)+third*float(7-firstWeight-secondWeight))/7;
                const auto pixel=project(viewport,point);
                double clearance=viewport.width();
                for (const auto &entry : session.model.value("segments").toArray()) {
                    const auto pair=entry.toArray();
                    const auto start=project(viewport,vectorOf(pair[0])),end=project(viewport,vectorOf(pair[1])),delta=end-start;
                    const double square=QPointF::dotProduct(delta,delta);
                    const double fraction=square>0?std::clamp(QPointF::dotProduct(pixel-start,delta)/square,0.0,1.0):0;
                    clearance=std::min(clearance,QLineF(pixel,start+fraction*delta).length());
                }
                if (clearance>bestClearance) { bestClearance=clearance; best=point; }
            }
        }
        require(bestClearance>12,"Face click must clear every projected native edge, including rear edges");
        return best;
    }

    QVector3D edgeMidpoint() const {
        const auto segments=session.model.value("segments").toArray();
        for (int index=0;index<segments.size();++index) {
            const auto pair=segments[index].toArray();
            require(pair.size()==2,"Kernel edge segment must have two endpoints");
            const auto first=vectorOf(pair[0]),second=vectorOf(pair[1]);
            const auto middle=(first+second)/2;
            if (std::abs(middle.z()-20)<0.001 && QLineF(project(viewport,first),project(viewport,second)).length()>40) return middle;
        }
        throw std::runtime_error("Real box must expose a long top edge");
    }
};
}

int main(int argc,char **argv) {
    qputenv("QT_QPA_PLATFORM","offscreen");
    qputenv("QSG_RHI_BACKEND","software");
    qputenv("QT_QUICK_BACKEND","software");
    qputenv("GENFORM_PORT","0");
    QApplication application(argc,argv);
    QStringList failures;
    int cases=0;
    const auto runCase=[&](const QString &name,const std::function<void()> &test) {
        ++cases;
        QTextStream(stdout)<<"RUN "<<name<<Qt::endl;
        try { test(); QTextStream(stdout)<<"PASS "<<name<<Qt::endl; }
        catch (const std::exception &error) {
            const auto failure=name+": "+QString::fromUtf8(error.what());
            failures.append(failure);
            QTextStream(stderr)<<"FAIL "<<failure<<Qt::endl;
        }
    };

    runCase("real face pick highlights one face rather than its owner",[] {
        Fixture fixture;
        const PersistentState before(fixture.session);
        const auto baseline=fixture.image();
        const auto facePoint=fixture.topFaceInterior();
        const auto chosen=fixture.click(facePoint);
        require(chosen.value("faces").toArray().size()==1 && chosen.value("edges").toArray().isEmpty(),"Face interior must pick one native face without an edge: "+QString::fromUtf8(jsonBytes(chosen)));
        const int face=chosen.value("faces").toArray().first().toInt(-1);
        const auto faceInfo=topology(fixture.session.model.value("faces").toArray(),face);
        require(chosen.value("feature")==fixture.body && faceInfo.value("feature")==fixture.body
            && std::abs(vectorOf(faceInfo.value("center")).z()-20)<0.001,"Face pick must retain the true top-face id and its owner");
        require(fixture.session.model.value("tri_face").toArray().contains(face),"Picked face must own actual rendered triangles");
        const auto faceImage=fixture.image();
        require(blue(fixture.sample(faceImage,facePoint)),"Selected top face must render blue");
        require(fixture.sample(faceImage,{10,-1.7f,8.3f})==fixture.sample(baseline,{10,-1.7f,8.3f}),"Unselected side of the same feature must retain its original pixels");
        fixture.controller->selectFeature(fixture.body);
        const auto featureImage=fixture.image();
        const int faceBlue=pixels(faceImage,blue),featureBlue=pixels(featureImage,blue);
        QTextStream(stdout)<<"blue_pixels face="<<faceBlue<<" feature="<<featureBlue<<Qt::endl;
        require(faceBlue>5000 && featureBlue>faceBlue*1.8,"Pure feature selection must cover substantially more blue pixels than a single real face");
        require(blue(fixture.sample(featureImage,{10,-1.7f,8.3f})),"Selecting the whole feature must also highlight its other visible side");
        fixture.controller->escape();
        require(fixture.image()==baseline,"Clearing face/feature selection must restore the exact original rendering");
        before.requireUnchanged(fixture.session);
    });

    runCase("real edge pick keeps owner without filling the box blue",[] {
        Fixture fixture;
        const PersistentState before(fixture.session);
        const auto baseline=fixture.image();
        const auto chosen=fixture.click(fixture.edgeMidpoint());
        require(chosen.value("edges").toArray().size()==1 && chosen.value("faces").toArray().isEmpty(),"Edge midpoint must pick one native edge");
        const int edge=chosen.value("edges").toArray().first().toInt(-1);
        const auto edgeInfo=topology(fixture.session.model.value("edges").toArray(),edge);
        const auto selected=fixture.image();
        require(pixels(selected,blue)<=pixels(baseline,blue)+40,"Edge selection must not paint its owner triangles blue");
        require(pixels(selected,orange)>40,"Selected native edge must render its orange edge highlight");
        require(fixture.sample(selected,{1.7f,-2.3f,20})==fixture.sample(baseline,{1.7f,-2.3f,20})
            && fixture.sample(selected,{10,-1.7f,8.3f})==fixture.sample(baseline,{10,-1.7f,8.3f}),"Edge selection must preserve both visible face interiors");
        fixture.controller->escape();
        require(fixture.image()==baseline,"Clearing edge selection must restore original pixels");
        before.requireUnchanged(fixture.session);
        require(chosen.value("feature")==fixture.body && edgeInfo.value("feature")==fixture.body,"Real edge table and viewport pick must retain the actual owning feature");
    });

    runCase("renderer scopes an owned native edge selection to the edge",[] {
        Fixture fixture;
        const PersistentState before(fixture.session);
        const auto baseline=fixture.image();
        const auto faces=fixture.session.model.value("faces").toArray();
        require(!faces.isEmpty(),"Renderer selection fixture must have real native faces");
        const auto face=faces.first().toObject();
        const auto edges=face.value("edges").toArray();
        require(face.value("feature")==fixture.body && !edges.isEmpty(),"Native face adjacency must supply a real owner and edge id");
        topology(fixture.session.model.value("edges").toArray(),edges.first().toInt(-1));
        fixture.viewport.setSelection({{"feature",face.value("feature")},{"edges",QJsonArray{edges.first()}},{"faces",QJsonArray{}}});
        const auto selected=fixture.image();
        require(pixels(selected,orange)>40,"Renderer must draw the selected real edge");
        require(pixels(selected,blue)<=pixels(baseline,blue)+40,"An edge with a real feature owner must not cause whole-feature blue fill");
        require(fixture.sample(selected,{1.7f,-2.3f,20})==fixture.sample(baseline,{1.7f,-2.3f,20})
            && fixture.sample(selected,{10,-1.7f,8.3f})==fixture.sample(baseline,{10,-1.7f,8.3f}),"Owned edge selection must preserve native face colors");
        fixture.viewport.setSelection({});
        require(fixture.image()==baseline,"Clearing renderer topology selection must restore every baseline pixel");
        before.requireUnchanged(fixture.session);
    });

    runCase("pure feature selection highlights all visible native faces",[] {
        Fixture fixture;
        const PersistentState before(fixture.session);
        const auto baseline=fixture.image();
        fixture.controller->selectFeature(fixture.body);
        require(fixture.session.selection.value("feature")==fixture.body && fixture.session.selection.value("faces").toArray().isEmpty()
            && fixture.session.selection.value("edges").toArray().isEmpty() && fixture.session.selection.value("vertices").toArray().isEmpty(),"Tree feature selection must contain no narrower topology");
        const auto selected=fixture.image();
        for (const auto &point : {QVector3D(1.7f,-2.3f,20),QVector3D(10,-1.7f,8.3f),QVector3D(-1.7f,-10,8.3f)})
            require(blue(fixture.sample(selected,point)),"Whole feature selection must highlight each of the three visible native faces");
        require(pixels(selected,blue)>50000,"Whole-box highlight must cover a real filled area");
        fixture.controller->escape();
        require(fixture.image()==baseline,"Feature deselection must restore the exact baseline");
        before.requireUnchanged(fixture.session);
    });

    runCase("wire check highlights use native edge owners and clear exactly",[] {
        Fixture fixture;
        const PersistentState before(fixture.session);
        int owned=0;
        for (const auto &entry : fixture.session.model.value("edges").toArray()) if (entry.toObject().value("feature")==fixture.body) ++owned;
        const auto facePoint=fixture.topFaceInterior();
        int minimumRed=900*700;
        for (const auto &style : {QString("wire"),QString("wireframe")}) {
            fixture.controller->setDisplayStyle(style);
            const auto baseline=fixture.image();
            require(pixels(baseline,red)==0 && fixture.sample(baseline,facePoint).alpha()==0,"Wire baseline must have no red edges or face fill");
            fixture.viewport.setCheckHighlights({fixture.body});
            const auto flagged=fixture.image();
            const int flaggedRed=pixels(flagged,red);
            minimumRed=std::min(minimumRed,flaggedRed);
            QTextStream(stdout)<<"style="<<style<<" native_owned_edges="<<owned<<" red_pixels="<<flaggedRed<<Qt::endl;
            require(fixture.sample(flagged,facePoint).alpha()==0,"Check edge highlight must not add shaded faces");
            fixture.controller->clearCheck();
            require(fixture.image()==baseline,"Production clearCheck must restore the exact original wire rendering");
            fixture.viewport.setCheckHighlights({"missing-feature"});
            require(fixture.image()==baseline,"Unknown check owner must not color unrelated native edges");
            fixture.viewport.setCheckHighlights({});
            require(fixture.image()==baseline,"Clearing the viewport check set must be reversible");
        }
        before.requireUnchanged(fixture.session);
        require(minimumRed>500,"Check highlight must paint actual red native edge segments in both wire styles");
        require(owned==12,"All twelve real box edges must expose their native feature owner");
    });

    runCase("check owner colors only its own edges in a two-feature solid",[] {
        Fixture fixture(true);
        const PersistentState before(fixture.session);
        fixture.controller->setDisplayStyle("wire");
        const auto baseline=fixture.image();
        QMap<QString,QPointF> points;
        const auto segments=fixture.session.model.value("segments").toArray(),identifiers=fixture.session.model.value("segment_edge").toArray();
        for (int index=0;index<segments.size();++index) {
            const auto owner=topology(fixture.session.model.value("edges").toArray(),identifiers[index].toInt(-1)).value("feature").toString();
            if (owner!=fixture.body && owner!=fixture.boss) continue;
            const auto pair=segments[index].toArray();
            const auto first=project(fixture.viewport,vectorOf(pair[0])),second=project(fixture.viewport,vectorOf(pair[1]));
            if (QLineF(first,second).length()>45 && !points.contains(owner)) points[owner]=(first+second)/2;
        }
        require(points.contains(fixture.body) && points.contains(fixture.boss),"Both real feature owners must be represented in native edge topology");
        const auto neighborhood=[&](const QImage &image,const QPointF &point) {
            return pixels(image.copy(QRect(point.toPoint()-QPoint(3,3),QSize(7,7))),red);
        };
        fixture.viewport.setCheckHighlights({fixture.boss});
        const auto flagged=fixture.image();
        require(neighborhood(flagged,points.value(fixture.boss))>4,"Flagged boss owner must paint its actual edge red");
        require(neighborhood(flagged,points.value(fixture.body))==0,"Unflagged base owner must retain its wire edge color");
        fixture.viewport.setCheckHighlights({});
        require(fixture.image()==baseline,"Clearing a single-feature check highlight must restore both owners");
        before.requireUnchanged(fixture.session);
    });

    runCase("material color follows refresh and clearing global appearance",[] {
        Fixture fixture;
        const PersistentState geometry(fixture.session);
        const auto brass=materialWithColor("#C9A24A"),copper=materialWithColor("#C07A4E");
        fixture.controller->setMaterial(brass.value("name").toString());
        fixture.controller->setAppearance("");
        require(!fixture.session.document.props.contains("color"),"Clearing global appearance must remove its document override");
        const auto brassImage=fixture.image();
        requireShade(fixture.sample(brassImage,{1.7f,-2.3f,20}),QColor(brass.value("color").toString()),"Cleared appearance must immediately render the active material color");
        fixture.controller->setMaterial(copper.value("name").toString());
        const auto copperImage=fixture.image();
        requireShade(fixture.sample(copperImage,{1.7f,-2.3f,20}),QColor(copper.value("color").toString()),"Material change must flow through production refresh into painted triangles");
        require(copperImage!=brassImage,"Distinct catalog material colors must produce distinct actual images");
        fixture.controller->setAppearance("#18c84f");
        requireShade(fixture.sample(fixture.image(),{1.7f,-2.3f,20}),QColor("#18c84f"),"Explicit global appearance must override the material in rendered pixels");
        fixture.controller->setAppearance("");
        require(fixture.image()==copperImage,"Clearing explicit appearance must restore material pixels exactly after refresh");
        require(fixture.session.document.dirty,"Explicit material/appearance commands must retain the normal document edit state");
        geometry.requireGeometry(fixture.session);
    });

    runCase("feature color paints only its owner and clears reversibly",[] {
        Fixture fixture(true);
        const PersistentState geometry(fixture.session);
        const auto baseline=fixture.image();
        const QVector3D bossPoint(1.3f,-1.9f,26),basePoint(10,-1.7f,8.3f);
        fixture.command("set_appearance",{{"features",QJsonArray{fixture.boss}},{"color","#d83ca8"}});
        require(fixture.session.document.props.value("feature_colors").toObject().value(fixture.boss)=="#d83ca8","Feature color must use the production feature_colors property");
        const auto painted=fixture.image();
        requireShade(fixture.sample(painted,bossPoint),QColor("#d83ca8"),"Native boss triangles must use the feature-specific color");
        require(fixture.sample(painted,basePoint)==fixture.sample(baseline,basePoint),"Feature color must preserve the unpainted owner's actual face pixels");
        require(painted!=baseline,"Setting feature color must affect the actual render");
        fixture.command("set_appearance",{{"features",QJsonArray{fixture.boss}},{"opacity",0.25}});
        const auto translucent=fixture.image();
        require(fixture.sample(translucent,bossPoint)!=fixture.sample(painted,bossPoint),"Per-feature opacity must change its owner's real painted pixels");
        require(fixture.sample(translucent,basePoint)==fixture.sample(baseline,basePoint),"Per-feature opacity must preserve the other owner's face pixels");
        fixture.command("set_appearance",{{"features",QJsonArray{fixture.boss}},{"opacity",1.0}});
        require(fixture.image()==painted,"Restoring feature opacity must preserve its independent color");
        fixture.command("set_appearance",{{"features",QJsonArray{fixture.boss}},{"color",""}});
        require(fixture.image()==baseline,"Clearing feature color must restore the complete original image");
        geometry.requireGeometry(fixture.session);
    });

    runCase("feature_opacity changes real compositing without touching geometry",[] {
        Fixture fixture;
        const PersistentState geometry(fixture.session);
        const QVector3D samplePoint(1.7f,-2.3f,20);
        fixture.command("set_appearance",{{"features",QJsonArray{fixture.body}},{"color","#d83ca8"}});
        const auto opaque=fixture.image();
        requireShade(fixture.sample(opaque,samplePoint),QColor("#d83ca8"),"Opacity fixture must begin with an opaque colored native face");
        int previousAlpha=0;
        QColor previousWhite=Qt::white;
        for (const double opacity : {0.05,0.25,0.65,1.0}) {
            fixture.command("set_appearance",{{"features",QJsonArray{fixture.body}},{"opacity",opacity}});
            const auto props=fixture.session.document.props;
            const auto shades=props.value("feature_opacity").toObject();
            require(opacity==1 ? !shades.contains(fixture.body) : std::abs(shades.value(fixture.body).toDouble()-opacity)<1e-9,"Opacity command must use props.feature_opacity and clear the identity override");
            require(props.value("feature_colors").toObject().value(fixture.body)=="#d83ca8","Opacity-only command must retain its feature color");
            const auto transparentImage=fixture.image(),whiteImage=fixture.image(Qt::white);
            const auto transparentPixel=fixture.sample(transparentImage,samplePoint),whitePixel=fixture.sample(whiteImage,samplePoint);
            const int distance=765-whitePixel.red()-whitePixel.green()-whitePixel.blue();
            QTextStream(stdout)<<"opacity="<<opacity<<" rendered_alpha="<<transparentPixel.alpha()<<" white_distance="<<distance<<Qt::endl;
            require(transparentPixel.alpha()>previousAlpha && distance>10 && whitePixel!=previousWhite,"Increasing real feature opacity must increase alpha and change actual compositing over white");
            require(whitePixel.alpha()==255,"Compositing onto opaque white must retain an opaque destination");
            const double alpha=transparentPixel.alphaF();
            require(std::abs(whitePixel.red()-(transparentPixel.red()*alpha+255*(1-alpha)))<4
                && std::abs(whitePixel.green()-(transparentPixel.green()*alpha+255*(1-alpha)))<4
                && std::abs(whitePixel.blue()-(transparentPixel.blue()*alpha+255*(1-alpha)))<4,"QPainter feature opacity must obey actual source-over pixel compositing");
            if (opacity<1) require(transparentPixel.alpha()<250 && transparentImage!=opaque,"Sub-unit feature opacity must affect real filled pixels");
            else require(transparentImage==opaque,"Restoring opacity one must restore the exact opaque image");
            previousAlpha=transparentPixel.alpha(); previousWhite=whitePixel;
        }
        geometry.requireGeometry(fixture.session);
    });

    QTextStream(stdout)<<QJsonDocument(QJsonObject{{"ok",failures.isEmpty()},{"cases",cases},{"passed",cases-failures.size()},
        {"failures",QJsonArray::fromStringList(failures)}}).toJson(QJsonDocument::Compact)<<Qt::endl;
    return failures.isEmpty()?0:1;
}
