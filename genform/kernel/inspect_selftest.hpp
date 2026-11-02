#pragma once

#if defined(GENFORM_INSPECT_SELFTEST) && defined(GENFORM_HAS_OCCT)
#include <QJsonObject>

namespace genform::kernel::native {
QJsonObject runInspectSelfTests();
}
#endif
