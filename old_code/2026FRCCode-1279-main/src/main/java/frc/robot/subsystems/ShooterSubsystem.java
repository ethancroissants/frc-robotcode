package frc.robot.subsystems;
     
import edu.wpi.first.wpilibj2.command.SubsystemBase;
import frc.robot.MotorControllers;

import com.ctre.phoenix6.controls.Follower;
import com.ctre.phoenix6.configs.Slot0Configs;
import com.ctre.phoenix6.configs.TalonFXConfiguration;
import com.ctre.phoenix6.hardware.TalonFX;
import com.ctre.phoenix6.signals.MotorAlignmentValue;
     
public class ShooterSubsystem extends SubsystemBase 
{
    private static final double SHOOTER_SPEED = 1.0; // Full speed
    private TalonFXConfiguration shooterMotorConfig = new TalonFXConfiguration();
    public Slot0Configs slot0Configs = new Slot0Configs();

    public ShooterSubsystem (){
    }
    // public void spinUpToSpeed() {
    //     shooterMotor.set(SHOOTER_SPEED);
    // }
     
    public boolean isAtSpeed() {
        // Simplified: Assume instant readiness or check velocity sensor
        return true;
    }
     
    public void fire() {
        // Trigger feeder or solenoid here
        System.out.println("Firing!");
    }
    
    public void stopShooter() {
        //shooterMotor.set(0.0);
    }
}