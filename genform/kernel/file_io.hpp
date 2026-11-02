#pragma once

#ifdef GENFORM_HAS_OCCT
#include <QString>
#include <TopoDS_Shape.hxx>

namespace genform::kernel::file_io {

void writeShape(const TopoDS_Shape &shape, const QString &path);
TopoDS_Shape readShape(const QString &path);

}
#endif
