#include "native.hpp"

#include <QRegularExpression>
#include <algorithm>
#include <limits>

namespace genform::kernel::native {
namespace {

class Expression {
public:
    Expression(QString text, const QMap<QString, double> &variables) : text_(std::move(text)), variables_(variables) {}
    double run() {
        const double result = sum();
        space();
        if (position_ != text_.size() || !std::isfinite(result)) fail("Invalid or non-finite expression: " + text_);
        return result;
    }
private:
    QString text_;
    const QMap<QString, double> &variables_;
    qsizetype position_ = 0;
    int depth_ = 0;
    void space() { while (position_ < text_.size() && text_[position_].isSpace()) ++position_; }
    bool take(QChar character) {
        space();
        if (position_ < text_.size() && text_[position_] == character) { ++position_; return true; }
        return false;
    }
    double sum() {
        double value = product();
        while (true) {
            if (take('+')) value += product();
            else if (take('-')) value -= product();
            else return value;
        }
    }
    double product() {
        double value = unary();
        while (true) {
            space();
            if (position_ + 1 < text_.size() && text_.mid(position_, 2) == "**") return value;
            if (take('*')) value *= unary();
            else if (take('/')) {
                const double divisor = unary();
                if (divisor == 0) fail("Division by zero in expression");
                value /= divisor;
            } else if (take('%')) {
                const double divisor = unary();
                if (divisor == 0) fail("Modulo by zero in expression");
                value -= std::floor(value / divisor) * divisor;
            } else return value;
        }
    }
    double unary() {
        if (++depth_ > 128) fail("Expression nesting limit exceeded");
        double value;
        if (take('+')) value = unary();
        else if (take('-')) value = -unary();
        else value = power();
        --depth_;
        return value;
    }
    double power() {
        double value = atom();
        space();
        bool exponent = take('^');
        if (!exponent && text_.mid(position_, 2) == "**") { position_ += 2; exponent = true; }
        if (exponent) value = std::pow(value, unary());
        return value;
    }
    double atom() {
        if (take('(')) {
            const double value = sum();
            if (!take(')')) fail("Missing ')' in expression");
            return value;
        }
        space();
        const qsizetype start = position_;
        if (position_ < text_.size() && (text_[position_].isDigit() || text_[position_] == '.')) {
            while (position_ < text_.size() && (text_[position_].isDigit() || text_[position_] == '.')) ++position_;
            if (position_ < text_.size() && (text_[position_] == 'e' || text_[position_] == 'E')) {
                ++position_;
                if (position_ < text_.size() && (text_[position_] == '+' || text_[position_] == '-')) ++position_;
                while (position_ < text_.size() && text_[position_].isDigit()) ++position_;
            }
            bool ok = false;
            const double value = text_.mid(start, position_ - start).toDouble(&ok);
            if (!ok) fail("Invalid number in expression");
            return value;
        }
        while (position_ < text_.size() && (text_[position_].isLetterOrNumber() || text_[position_] == '_')) ++position_;
        const QString name = text_.mid(start, position_ - start);
        if (name.isEmpty()) fail("Expected a value in expression: " + text_);
        if (!take('(')) {
            if (variables_.contains(name)) return variables_[name];
            if (name == "pi") return std::acos(-1.0);
            if (name == "e") return std::exp(1.0);
            fail("Unknown expression variable: " + name);
        }
        std::vector<double> arguments;
        if (!take(')')) {
            do { arguments.push_back(sum()); } while (take(','));
            if (!take(')')) fail("Missing ')' after function arguments");
        }
        if (arguments.size() == 1) {
            const double value = arguments.front();
            if (name == "sin") return std::sin(value);
            if (name == "cos") return std::cos(value);
            if (name == "tan") return std::tan(value);
            if (name == "asin") return std::asin(value);
            if (name == "acos") return std::acos(value);
            if (name == "atan") return std::atan(value);
            if (name == "sinh") return std::sinh(value);
            if (name == "cosh") return std::cosh(value);
            if (name == "tanh") return std::tanh(value);
            if (name == "sqrt") return std::sqrt(value);
            if (name == "exp") return std::exp(value);
            if (name == "log") return std::log(value);
            if (name == "log10") return std::log10(value);
            if (name == "floor") return std::floor(value);
            if (name == "ceil") return std::ceil(value);
            if (name == "abs") return std::abs(value);
            if (name == "radians") return value * std::acos(-1.0) / 180;
            if (name == "degrees") return value * 180 / std::acos(-1.0);
        }
        if (arguments.size() == 2) {
            if (name == "atan2") return std::atan2(arguments[0], arguments[1]);
            if (name == "pow") return std::pow(arguments[0], arguments[1]);
            if (name == "log") return std::log(arguments[0]) / std::log(arguments[1]);
        }
        if (!arguments.empty()) {
            if (name == "min") return *std::min_element(arguments.begin(), arguments.end());
            if (name == "max") return *std::max_element(arguments.begin(), arguments.end());
        }
        fail("Unknown function or invalid argument count: " + name);
        return 0;
    }
};
}

double number(const QJsonObject &object, const QString &key, double fallback, bool positive) {
    const QJsonValue value = object.value(key);
    bool ok = value.isDouble();
    double result = value.isUndefined() || value.isNull() ? fallback : value.toDouble();
    if (value.isString()) result = value.toString().toDouble(&ok);
    if ((!value.isUndefined() && !value.isNull() && !ok) || !std::isfinite(result) || (positive && result <= 0))
        fail("Invalid numeric parameter: " + key);
    return result;
}

double evaluate(const QString &expression, const QMap<QString, double> &variables) {
    if (expression.size() > 16384) fail("Expression length limit exceeded");
    return Expression(expression, variables).run();
}

QJsonValue resolve(const QJsonValue &value, const QMap<QString, double> &variables) {
    if (value.isObject()) {
        QJsonObject result = value.toObject();
        for (auto entry = result.begin(); entry != result.end(); ++entry) entry.value() = resolve(entry.value(), variables);
        return result;
    }
    if (value.isArray()) {
        QJsonArray result;
        for (const auto &entry : value.toArray()) result.append(resolve(entry, variables));
        return result;
    }
    if (value.isString() && value.toString().trimmed().startsWith('=')) return evaluate(value.toString().trimmed().mid(1), variables);
    return value;
}
}
