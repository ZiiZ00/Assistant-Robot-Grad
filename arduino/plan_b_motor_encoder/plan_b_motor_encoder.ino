/*
  Grand Egyptian Museum Robot - Plan B Arduino firmware
  Input:  CMD F 120 / CMD B 120 / CMD L 100 / CMD R 100 / CMD S 0
  Output: ENC L=<ticks> R=<ticks> every 100 ms
  Encoder signals connected to the Uno must be 5 V logic-safe.
*/

const uint8_t DIR1_PIN = 4;
const uint8_t PWM1_PIN = 5;
const uint8_t DIR2_PIN = 7;
const uint8_t PWM2_PIN = 6;
const uint8_t LEFT_ENCODER_A_PIN = 2;
const uint8_t LEFT_ENCODER_B_PIN = 8;
const uint8_t RIGHT_ENCODER_A_PIN = 3;
const uint8_t RIGHT_ENCODER_B_PIN = 9;

const bool INVERT_LEFT_MOTOR = false;
const bool INVERT_RIGHT_MOTOR = false;
volatile long leftTicks = 0;
volatile long rightTicks = 0;
unsigned long lastEncoderReportMs = 0;
unsigned long lastValidCommandMs = 0;
const unsigned long COMMAND_WATCHDOG_MS = 1200;
char commandBuffer[24];
uint8_t commandLength = 0;

void leftEncoderISR() {
  leftTicks += digitalRead(LEFT_ENCODER_B_PIN) == HIGH ? 1 : -1;
}

void rightEncoderISR() {
  rightTicks += digitalRead(RIGHT_ENCODER_B_PIN) == HIGH ? 1 : -1;
}

void setOneMotor(uint8_t dirPin, uint8_t pwmPin, int signedSpeed, bool invert) {
  signedSpeed = constrain(signedSpeed, -255, 255);
  if (invert) signedSpeed = -signedSpeed;
  digitalWrite(dirPin, signedSpeed >= 0 ? HIGH : LOW);
  analogWrite(pwmPin, abs(signedSpeed));
}

void setMotors(int leftSpeed, int rightSpeed) {
  setOneMotor(DIR1_PIN, PWM1_PIN, leftSpeed, INVERT_LEFT_MOTOR);
  setOneMotor(DIR2_PIN, PWM2_PIN, rightSpeed, INVERT_RIGHT_MOTOR);
}

void stopMotors() {
  analogWrite(PWM1_PIN, 0);
  analogWrite(PWM2_PIN, 0);
}

void handleCommand(const char *line) {
  char direction = 0;
  int speedValue = 0;
  if (sscanf(line, "CMD %c %d", &direction, &speedValue) != 2) return;
  speedValue = constrain(speedValue, 0, 255);
  switch (direction) {
    case 'F': setMotors(speedValue, speedValue); break;
    case 'B': setMotors(-speedValue, -speedValue); break;
    case 'L': setMotors(-speedValue, speedValue); break;
    case 'R': setMotors(speedValue, -speedValue); break;
    case 'S': stopMotors(); break;
    default: return;
  }
  lastValidCommandMs = millis();
}

void readSerialCommands() {
  while (Serial.available() > 0) {
    char incoming = Serial.read();
    if (incoming == '\n' || incoming == '\r') {
      if (commandLength > 0) {
        commandBuffer[commandLength] = '\0';
        handleCommand(commandBuffer);
        commandLength = 0;
      }
    } else if (commandLength < sizeof(commandBuffer) - 1) {
      commandBuffer[commandLength++] = incoming;
    } else {
      commandLength = 0;
    }
  }
}

void reportEncoders() {
  if (millis() - lastEncoderReportMs < 100) return;
  lastEncoderReportMs = millis();
  noInterrupts();
  long leftSnapshot = leftTicks;
  long rightSnapshot = rightTicks;
  interrupts();
  Serial.print("ENC L=");
  Serial.print(leftSnapshot);
  Serial.print(" R=");
  Serial.println(rightSnapshot);
}

void setup() {
  pinMode(DIR1_PIN, OUTPUT);
  pinMode(PWM1_PIN, OUTPUT);
  pinMode(DIR2_PIN, OUTPUT);
  pinMode(PWM2_PIN, OUTPUT);
  pinMode(LEFT_ENCODER_A_PIN, INPUT_PULLUP);
  pinMode(LEFT_ENCODER_B_PIN, INPUT_PULLUP);
  pinMode(RIGHT_ENCODER_A_PIN, INPUT_PULLUP);
  pinMode(RIGHT_ENCODER_B_PIN, INPUT_PULLUP);
  stopMotors();
  attachInterrupt(digitalPinToInterrupt(LEFT_ENCODER_A_PIN), leftEncoderISR, RISING);
  attachInterrupt(digitalPinToInterrupt(RIGHT_ENCODER_A_PIN), rightEncoderISR, RISING);
  Serial.begin(115200);
  lastValidCommandMs = millis();
}

void loop() {
  readSerialCommands();
  reportEncoders();
  if (millis() - lastValidCommandMs > COMMAND_WATCHDOG_MS) stopMotors();
}
