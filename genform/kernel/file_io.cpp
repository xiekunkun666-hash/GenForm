#include "file_io.hpp"
#include "native.hpp"

#ifdef GENFORM_HAS_OCCT
#include <BRep_Builder.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepTools.hxx>
#include <IFSelect_ReturnStatus.hxx>
#include <STEPConstruct_ExternRefs.hxx>
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#include <Standard_Failure.hxx>
#include <StlAPI_Reader.hxx>
#include <StlAPI_Writer.hxx>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSaveFile>
#include <QTemporaryDir>
#include <array>
#include <istream>
#include <memory>
#include <ostream>
#include <streambuf>

namespace genform::kernel::file_io {
namespace {
using native::fail;

class InputBuffer : public std::streambuf {
public:
    explicit InputBuffer(QFile &file) : file_(file) {}

protected:
    int_type underflow() override {
        if (gptr() && gptr() < egptr()) return traits_type::to_int_type(*gptr());
        const auto count = file_.read(buffer_.data(), static_cast<qint64>(buffer_.size()));
        if (count <= 0) return traits_type::eof();
        setg(buffer_.data(), buffer_.data(), buffer_.data() + count);
        return traits_type::to_int_type(*gptr());
    }

    pos_type seekoff(off_type offset, std::ios_base::seekdir direction, std::ios_base::openmode mode) override {
        if (!(mode & std::ios_base::in)) return pos_type(off_type(-1));
        const auto unread = gptr() ? egptr() - gptr() : 0;
        const qint64 origin = direction == std::ios_base::beg ? 0
            : direction == std::ios_base::end ? file_.size() : file_.pos() - unread;
        if (!file_.seek(origin + offset)) return pos_type(off_type(-1));
        setg(nullptr, nullptr, nullptr);
        return pos_type(file_.pos());
    }

    pos_type seekpos(pos_type position, std::ios_base::openmode mode) override {
        return seekoff(off_type(position), std::ios_base::beg, mode);
    }

private:
    QFile &file_;
    std::array<char, 65536> buffer_;
};

class OutputBuffer : public std::streambuf {
public:
    explicit OutputBuffer(QSaveFile &file) : file_(file) {}

protected:
    std::streamsize xsputn(const char *data, std::streamsize size) override {
        std::streamsize written = 0;
        while (written < size) {
            const auto count = file_.write(data + written, size - written);
            if (count <= 0) break;
            written += count;
        }
        return written;
    }

    int_type overflow(int_type character) override {
        if (traits_type::eq_int_type(character, traits_type::eof())) return traits_type::not_eof(character);
        const char value = traits_type::to_char_type(character);
        return xsputn(&value, 1) == 1 ? character : traits_type::eof();
    }

    int sync() override { return file_.flush() ? 0 : -1; }

private:
    QSaveFile &file_;
};

bool asciiPath(const QString &path) {
    for (const auto character : path) if (character.unicode() > 127) return false;
    return true;
}

std::unique_ptr<QTemporaryDir> stagingDirectory() {
    const QStringList roots{QDir::tempPath(), QCoreApplication::applicationDirPath(), QDir::homePath()};
    for (const auto &root : roots) {
        if (root.isEmpty() || !asciiPath(root)) continue;
        auto temporary = std::make_unique<QTemporaryDir>(QDir(root).filePath("genform-occt-XXXXXX"));
        if (temporary->isValid()) return temporary;
    }
    fail("Cannot create an ASCII temporary directory for OpenCascade STL I/O");
    return {};
}

void copyBytes(QFile &source, QIODevice &destination, const QString &path) {
    std::array<char, 65536> buffer;
    while (true) {
        const auto count = source.read(buffer.data(), static_cast<qint64>(buffer.size()));
        if (count < 0) fail("Cannot read file " + path + ": " + source.errorString());
        if (count == 0) break;
        qint64 written = 0;
        while (written < count) {
            const auto copied = destination.write(buffer.data() + written, count - written);
            if (copied <= 0) fail("Cannot write file " + path + ": " + destination.errorString());
            written += copied;
        }
    }
}

QString format(const QString &path) {
    if (path.isEmpty() || path.contains(QChar(u'\0'))) fail("File path must be nonempty and contain no NUL characters");
    const auto suffix = QFileInfo(path).suffix().toLower();
    if (suffix != "step" && suffix != "stp" && suffix != "stl" && suffix != "brep")
        fail("File format must be .step, .stp, .stl or .brep");
    return suffix;
}

QString occtMessage(const Standard_Failure &error) {
    return QString::fromUtf8(error.GetMessageString() ? error.GetMessageString() : "unknown failure");
}
}

void writeShape(const TopoDS_Shape &shape, const QString &path) {
    const auto suffix = format(path);
    if (shape.IsNull()) fail("There is no body to export");
    QSaveFile destination(path);
    destination.setDirectWriteFallback(false);
    if (!destination.open(QIODevice::WriteOnly)) fail("Cannot export file " + path + ": " + destination.errorString());
    try {
        OutputBuffer buffer(destination);
        std::ostream stream(&buffer);
        if (suffix == "step" || suffix == "stp") {
            STEPControl_Writer writer;
            if (writer.Transfer(shape, STEPControl_AsIs) != IFSelect_RetDone || writer.WriteStream(stream) != IFSelect_RetDone)
                fail("STEP export failed: " + path);
        } else if (suffix == "brep") {
            BRepTools::Write(shape, stream);
        } else {
            BRepMesh_IncrementalMesh mesh(shape, 0.05, false, 0.2, true);
            if (!mesh.IsDone()) fail("STL tessellation failed");
            const auto temporary = stagingDirectory();
            const auto stagedPath = temporary->filePath("shape.stl");
            const auto encoded = stagedPath.toLatin1();
            StlAPI_Writer writer;
            writer.ASCIIMode() = false;
            if (!writer.Write(shape, encoded.constData())) fail("STL export failed: " + path);
            QFile staged(stagedPath);
            if (!staged.open(QIODevice::ReadOnly) || staged.size() <= 84) fail("STL export produced no mesh: " + path);
            copyBytes(staged, destination, path);
        }
        stream.flush();
        if (!stream.good() || destination.error() != QFileDevice::NoError || destination.pos() <= 0)
            fail("Export write failed for " + path + ": " + destination.errorString());
        if (!destination.commit()) fail("Cannot commit exported file " + path + ": " + destination.errorString());
    } catch (const Standard_Failure &error) {
        fail("OpenCascade export failed: " + occtMessage(error));
    }
}

TopoDS_Shape readShape(const QString &path) {
    const auto suffix = format(path);
    const auto originalPath = QFileInfo(path).absoluteFilePath();
    QFile source(originalPath);
    if (!source.open(QIODevice::ReadOnly)) fail("Cannot import file " + path + ": " + source.errorString());
    try {
        TopoDS_Shape result;
        if (suffix == "stl") {
            const auto temporary = stagingDirectory();
            const auto stagedPath = temporary->filePath("shape.stl");
            QFile staged(stagedPath);
            if (!staged.open(QIODevice::WriteOnly)) fail("Cannot stage STL import: " + staged.errorString());
            copyBytes(source, staged, path);
            if (!staged.flush()) fail("Cannot stage STL import: " + staged.errorString());
            staged.close();
            StlAPI_Reader reader;
            const auto encoded = stagedPath.toLatin1();
            if (!reader.Read(result, encoded.constData())) fail("STL import failed: " + path);
        } else {
            InputBuffer buffer(source);
            std::istream stream(&buffer);
            if (suffix == "step" || suffix == "stp") {
                STEPControl_Reader reader;
                const auto identity = originalPath.toUtf8();
                if (reader.ReadStream(identity.constData(), stream) != IFSelect_RetDone) fail("STEP import failed: " + path);
                STEPConstruct_ExternRefs references(reader.WS());
                references.LoadExternRefs();
                if (references.NbExternRefs() > 0)
                    fail("STEP import contains external references; native solid import does not resolve external files: " + originalPath);
                if (reader.TransferRoots() < 1) fail("STEP file contains no transferable shapes: " + path);
                result = reader.OneShape();
            } else {
                BRep_Builder builder;
                BRepTools::Read(result, stream, builder);
            }
            if (stream.bad()) fail("Import read failed: " + path);
        }
        if (source.error() != QFileDevice::NoError) fail("Import read failed for " + path + ": " + source.errorString());
        if (result.IsNull()) fail("Import file contains no shape: " + path);
        return result;
    } catch (const Standard_Failure &error) {
        fail("OpenCascade import failed: " + occtMessage(error));
    }
    return {};
}
}
#endif
