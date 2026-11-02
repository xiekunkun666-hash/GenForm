#include "genform/kernel/file_io.hpp"
#include "genform/kernel/kernel.hpp"

#include <QCoreApplication>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QMap>
#include <QTemporaryDir>
#include <QTextStream>
#include <cmath>
#include <functional>
#include <stdexcept>

#ifdef GENFORM_HAS_OCCT
#include <BRepGProp.hxx>
#include <BRepBuilderAPI_MakeVertex.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <GProp_GProps.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <STEPConstruct_ExternRefs.hxx>
#include <STEPControl_Writer.hxx>
#include <StepBasic_ProductDefinition.hxx>
#include <StepData_StepModel.hxx>
#include <Standard_Failure.hxx>
#include <QtEndian>
#include <sstream>
#ifdef Q_OS_WIN
#include <qt_windows.h>
#endif
#endif

namespace {
int checks = 0;

void require(bool condition, const QString &message) {
    ++checks;
    if (!condition) throw std::runtime_error(message.toStdString());
}

#ifdef GENFORM_HAS_OCCT
void rejects(const std::function<void()> &operation, const QString &fragment = {}) {
    bool rejected = false;
    try {
        operation();
    } catch (const std::exception &error) {
        const auto message = QString::fromUtf8(error.what());
        rejected = !message.isEmpty() && (fragment.isEmpty() || message.contains(fragment));
    }
    require(rejected, "Expected an explicit failure containing: " + fragment);
}

QByteArray readBytes(const QString &path) {
    QFile file(path);
    require(file.open(QIODevice::ReadOnly), "Cannot read fixture: " + path);
    const auto bytes = file.readAll();
    require(file.error() == QFileDevice::NoError, "Fixture read error: " + path);
    return bytes;
}

void writeBytes(const QString &path, const QByteArray &bytes) {
    QFile file(path);
    require(file.open(QIODevice::WriteOnly), "Cannot write fixture: " + path);
    require(file.write(bytes) == bytes.size() && file.flush(), "Fixture short write: " + path);
}

QMap<QString, QByteArray> snapshot(const QString &root) {
    QMap<QString, QByteArray> result;
    QDirIterator iterator(root, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden, QDirIterator::Subdirectories);
    while (iterator.hasNext()) {
        iterator.next();
        const auto info = iterator.fileInfo();
        const auto relative = QDir(root).relativeFilePath(info.absoluteFilePath());
        if (info.isDir()) result.insert(relative + "/", {});
        else result.insert(relative, readBytes(info.absoluteFilePath()));
    }
    return result;
}

QStringList stagingEntries(const QString &root) {
    return QDir(root).entryList({"genform-occt-*"}, QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
}

#ifdef Q_OS_WIN
class LockedTarget {
public:
    explicit LockedTarget(const QString &path)
        : handle_(CreateFileW(reinterpret_cast<LPCWSTR>(path.utf16()), GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr)) {
        require(handle_ != INVALID_HANDLE_VALUE, "Cannot lock Windows export target");
    }
    ~LockedTarget() { CloseHandle(handle_); }
    LockedTarget(const LockedTarget &) = delete;
    LockedTarget &operator=(const LockedTarget &) = delete;

private:
    HANDLE handle_;
};
#endif

void volume(const TopoDS_Shape &shape, double expected) {
    GProp_GProps properties;
    BRepGProp::VolumeProperties(shape, properties);
    require(std::isfinite(properties.Mass()) && std::abs(properties.Mass() - expected) < 1e-5,
        QString("Expected volume %1, got %2").arg(expected).arg(properties.Mass()));
}

QByteArray referencedStep(const TopoDS_Shape &shape) {
    STEPControl_Writer writer;
    require(writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone, "Cannot create STEP reference fixture");
    Handle(StepBasic_ProductDefinition) product;
    const auto model = writer.Model();
    for (int index = 1; index <= model->NbEntities() && product.IsNull(); ++index)
        product = Handle(StepBasic_ProductDefinition)::DownCast(model->Value(index));
    require(!product.IsNull(), "STEP fixture has no product definition");
    STEPConstruct_ExternRefs references(writer.WS());
    require(references.AddExternRef("parts/child.step", product, "STEP AP214") > 0, "Cannot add STEP external reference");
    require(references.WriteExternRefs(1) > 0, "Cannot write STEP external reference");
    std::ostringstream stream;
    require(writer.WriteStream(stream) == IFSelect_RetDone && stream.good(), "Cannot serialize referenced STEP fixture");
    const auto bytes = stream.str();
    return QByteArray(bytes.data(), static_cast<qsizetype>(bytes.size()));
}

void fileTests() {
    using genform::kernel::file_io::readShape;
    using genform::kernel::file_io::writeShape;
    QTemporaryDir temporary;
    require(temporary.isValid(), "Temporary directory unavailable");
    const auto directory = temporary.filePath(QStringLiteral("中文目录/零件 📐"));
    require(QDir().mkpath(directory), "Cannot create Unicode fixture directory");
    const auto tempBefore = stagingEntries(QDir::tempPath());
    const auto appBefore = stagingEntries(QCoreApplication::applicationDirPath());
    const auto homeBefore = stagingEntries(QDir::homePath());
    const auto shape = BRepPrimAPI_MakeBox(2, 3, 4).Shape();
    QStringList expectedFiles;
    for (const auto &extension : {QString("STEP"), QString("stp"), QString("stl"), QString("brep")}) {
        const auto name = QStringLiteral("零件模型.") + extension;
        const auto path = QDir(directory).filePath(name);
        writeShape(shape, path);
        const auto bytes = readBytes(path);
        require(!bytes.isEmpty(), "Export succeeded without the intended Unicode file: " + path);
        if (extension == "STEP" || extension == "stp") require(bytes.startsWith("ISO-10303-21;"), "STEP export format changed");
        else if (extension == "brep") require(bytes.contains("CASCADE Topology"), "BREP export format changed");
        else {
            require(bytes.size() >= 84, "STL binary header missing");
            const auto triangles = qFromLittleEndian<quint32>(reinterpret_cast<const uchar *>(bytes.constData() + 80));
            require(triangles > 0 && bytes.size() == 84 + 50 * static_cast<qint64>(triangles), "STL must remain binary");
        }
        const auto imported = readShape(path);
        require(!imported.IsNull(), "Unicode roundtrip returned no shape");
        if (extension != "stl") volume(imported, 24);
        writeBytes(path, "existing file sentinel");
        writeShape(shape, path);
        require(readBytes(path) != "existing file sentinel", "Successful export did not replace the target");
        expectedFiles.append(name);
        const auto beforeNull = snapshot(temporary.path());
        rejects([&] { writeShape({}, path); });
        require(snapshot(temporary.path()) == beforeNull, "Null-shape export damaged an existing target");
#ifdef Q_OS_WIN
        {
            const LockedTarget lock(path);
            const auto beforeLocked = snapshot(temporary.path());
            rejects([&] { writeShape(shape, path); }, "commit");
            require(snapshot(temporary.path()) == beforeLocked, "Failed atomic commit damaged an existing target or leaked temporary files");
        }
#endif
        const auto beforeFailure = snapshot(temporary.path());
        const auto blocked = QDir(directory).filePath(QStringLiteral("已存在目录.") + extension);
        require(QDir().mkdir(blocked), "Cannot create blocked target fixture");
        const auto beforeBlocked = snapshot(temporary.path());
        rejects([&] { writeShape(shape, blocked); });
        require(snapshot(temporary.path()) == beforeBlocked, "Failed directory export polluted the directory");
        require(QDir().rmdir(blocked), "Cannot remove blocked target fixture");
        const auto missingParent = QDir(directory).filePath(QStringLiteral("不存在/零件.") + extension);
        rejects([&] { writeShape(shape, missingParent); });
        require(snapshot(temporary.path()) == beforeFailure, "Failed export changed existing files or created stray names");
        const auto invalid = QDir(directory).filePath(QStringLiteral("损坏文件.") + extension);
        writeBytes(invalid, "not a CAD file\n");
        const auto beforeImport = snapshot(temporary.path());
        rejects([&] { readShape(invalid); });
        rejects([&] { readShape(missingParent); });
        require(snapshot(temporary.path()) == beforeImport, "Failed import polluted the directory");
        require(QFile::remove(invalid), "Cannot remove invalid fixture");
    }
    expectedFiles.sort();
    require(QDir(directory).entryList(QDir::Files | QDir::Hidden, QDir::Name) == expectedFiles,
        "Unexpected or mojibake files exist beside the Unicode targets");
    const auto stlPath = QDir(directory).filePath(QStringLiteral("零件模型.stl"));
    const auto beforeTessellation = snapshot(temporary.path());
    const auto vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(0, 0, 0)).Shape();
    rejects([&] { writeShape(vertex, stlPath); }, "STL");
    require(snapshot(temporary.path()) == beforeTessellation, "Failed STL serialization damaged an existing target");

    const auto stepPath = QDir(directory).filePath(QStringLiteral("零件模型.STEP"));
    genform::kernel::Kernel kernel;
    const QJsonArray features{QJsonObject{{"id", "unicode_import"}, {"type", "import_step"},
        {"params", QJsonObject{{"path", stepPath}, {"scale", 2}, {"dx", 7}}}}};
    const auto built = kernel.build(features);
    require(built["status"].toObject()["unicode_import"] == "ok" && built["has_body"].toBool(), "Chinese STEP feature import failed");
    require(std::abs(kernel.query("properties")["volume"].toDouble() - 192) < 1e-5, "STEP import transforms changed");
    const auto publicExport = QDir(directory).filePath(QStringLiteral("内核导出.step"));
    kernel.exportFile(publicExport);
    volume(readShape(publicExport), 192);
    const auto protectedPath = QDir(directory).filePath(QStringLiteral("现有文件.xyz"));
    writeBytes(protectedPath, "keep this existing file");
    const auto protectedSnapshot = snapshot(temporary.path());
    rejects([&] { kernel.exportFile(protectedPath); });
    rejects([&] { writeShape(shape, QString()); });
    auto embeddedNul = stepPath;
    embeddedNul.append(QChar(u'\0')).append(".step");
    rejects([&] { writeShape(shape, embeddedNul); });
    rejects([&] { readShape(embeddedNul); });
    require(snapshot(temporary.path()) == protectedSnapshot, "Invalid paths damaged files");

    const auto referenced = QDir(directory).filePath(QStringLiteral("带外部引用.step"));
    writeBytes(referenced, referencedStep(shape));
    const auto referencedSnapshot = snapshot(temporary.path());
    rejects([&] { readShape(referenced); }, "external references");
    require(snapshot(temporary.path()) == referencedSnapshot, "Referenced STEP import changed source files");
    require(stagingEntries(QDir::tempPath()) == tempBefore, "STL temporary directory leaked");
    require(stagingEntries(QCoreApplication::applicationDirPath()) == appBefore, "Application staging directory leaked");
    require(stagingEntries(QDir::homePath()) == homeBefore, "Home staging directory leaked");
}
#endif
}

int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    try {
#ifdef GENFORM_HAS_OCCT
        fileTests();
#else
        require(!genform::kernel::Kernel::available(), "OCCT availability mismatch");
#endif
        QTextStream(stdout) << "File I/O checks passed: " << checks << '\n';
        return 0;
#ifdef GENFORM_HAS_OCCT
    } catch (const Standard_Failure &error) {
        QTextStream(stderr) << "OCCT test failure: " << error.GetMessageString() << '\n';
        return 1;
#endif
    } catch (const std::exception &error) {
        QTextStream(stderr) << "File I/O test failure: " << error.what() << '\n';
        return 1;
    }
}
